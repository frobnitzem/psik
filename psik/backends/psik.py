from typing import List, Optional, Set, Tuple
import asyncio
import os
import sys
import json
from pathlib import Path
from shlex import quote
import logging
_logger = logging.getLogger(__name__)

try:
    from certified import Certified # type: ignore[import-not-found]
except ImportError:
    Certified = None
import aiohttp

from pydantic import BaseModel
import psik
from ..job import Job
from ..config import Config
from ..models import (
    JobState,
    JobSpec,
    ExtraInfo,
    BackendConfig,
)
from ..console import runcmd
from ..zipstr import dir_to_str

from .slurm import mk_args

class JobStepInfo(BaseModel):
    #jobid   : str
    #name    : str
    updated : float
    jobndx  : int
    state   : JobState
    info    : str

use_mtls = True

""" TODO: consider trapping errors in a generic way.

async def make_request(fn, *args, **kws):
    async with fn(*args, **kws) as response:
        try:
            response.raise_for_status()
            return await response.json()

        except aiohttp.ClientResponseError as e:
            # Read the raw error text from the server response
            error_text = await response.json()

            _logger.error(f"HTTP Error {e.status}: {e.message}")
            _logger.error(f"API Error Details: {error_text}")
            raise
"""

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    POST this jobspec to the API.

    Attributes:

      remote_url: URL of psik_api
      remote_backend: name of backend to use on remote side
      next: job.attributes to forward to API (string which gets parsed to json)

    TODO: use submit=False if there are files to send.
    """
    assert job.spec.directory is not None
    # detect files_to_send in job.spec.directory
    files_to_send = False
    if job.spec.directory:
        dir_path = Path(job.spec.directory)
        if dir_path.is_dir():
            # Check if there are any files in the directory (excluding hidden files)
            if any(f.is_file() for f in dir_path.iterdir() if not f.name.startswith('.')):
                files_to_send = True

    # job.info.backend.attributes["remote_url"] = remote URL
    # job.info.backend.attributes["remote_backend"] = remote backend

    # setup job for the remote site
    spec = job.spec.copy()

    remote_url = job.info.backend.attributes["remote_url"]
    try:
        spec.backend = job.info.backend.attributes["remote_backend"]
    except KeyError:
        spec.backend = "default"

    spec.attributes = json.loads( job.info.backend.attributes.get("next", "{}") )

    spec.directory = None
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        assert Certified is not None, "certified package is required for mTLS"
        cert = Certified()
    else:
        cert = aiohttp

    closing = []
    try:
        async with cert.ClientSession(
                        base_url=remote_url,
                        headers=headers
                    ) as client:
            params = {"submit": "true"}
            if files_to_send:
                # 1. just allocate the jobid
                params["submit"] = "false"
            resp = await client.post("/v3/jobs", json=spec.model_dump(), params=params)
            result = await resp.json()
            if resp.status//100 != 2:
                _logger.error("Error submitting job script to %s: %s", remote_url, result)
                return None

            jobid = result
            if files_to_send:
                # 2. Prepare files for multipart upload
                dir_path = Path(job.spec.directory)
                data = aiohttp.FormData()
                for f in dir_path.rglob('*'):
                    if f.is_file() and not f.name.startswith('.'):
                        # Use relative path as filename
                        rel_path = str(f.relative_to(dir_path))
                        obj = open(f, "rb")
                        data.add_field('files',
                                       filename=str(rel_path),
                                       value=obj)
                        closing.append(obj)

                # 3. Post to files.
                resp = await client.post(f"/v3/jobs/{jobid}/files", data=data)
                if resp.status // 100 != 2:
                    result_files = await resp.json()
                    _logger.error("Error uploading files to %s: %s", remote_url, result_files)
                    return None

                # 3. Release the job to the queue.
                resp = await client.post(f"/v3/jobs/{jobid}/start")
                if resp.status // 100 != 2:
                    result = await resp.json()
                    _logger.error("Error starting job %s at %s: %s", jobid, remote_url, result)
                    return None
    except Exception as err:
        _logger.error("Error submitting job script to %s: %s", remote_url, err)
        return None
    finally:
        for obj in closing:
            obj.close()

    return jobid


async def cancel(job: Job) -> None:
    jobinfos = await job.live_ids()
    remote_url = job.info.backend.attributes["remote_url"]
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        assert Certified is not None, "certified package is required for mTLS"
        cert = Certified()
    else:
        cert = aiohttp

    try:
        async with cert.ClientSession(
                        base_url=remote_url,
                        headers=headers
                    ) as client:
            for id in jobinfos:
                resp = await client.delete(f"/v3/jobs/{id}")
                if resp.status//100 != 2:
                    err = await resp.json()
                    _logger.warning("Error returned from %s during cancel %s: %s", remote_url, id, err)
    except Exception as err:
        _logger.error("Error connecting to %s: %s", remote_url, err)


async def update_status(job: Job, history: List[JobStepInfo]):
    # filter events we have seen
    events: Set[Tuple[int,JobState]] = set()
    for trs in job.history:
        events.add( (trs.jobndx, trs.state) )

    updated = False
    for trs in history:
        key = (trs.jobndx, trs.state)
        if key in events: # we already know about this transition
            print(f"x {trs}")
            continue
        updated = True
        print(f"- {trs}")
        events.add(key)
        await job.reached(trs.jobndx, trs.state, trs.info,
                          backdate=trs.updated)

    return updated


async def poll(job: Job) -> None:
    remote_url = job.info.backend.attributes["remote_url"]
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        assert Certified is not None, "certified package is required for mTLS"
        cert = Certified()
    else:
        cert = aiohttp

    local_dir = Path(job.base)

    jobid = "" # Determine jobid for last queued jobndx
    jobndx = 0
    for trs in job.history:
        if trs.state == JobState.queued:
            jobid = trs.info
            jobndx = trs.jobndx
    if jobid == "":
        raise ValueError("Job has not been queued.")

    try:
        async with cert.ClientSession(
                        base_url=remote_url,
                        headers=headers
                    ) as client:
            resp = await client.get(f"/v3/jobs/{jobid}")
            if resp.status//100 != 2:
                err = await resp.json()
                _logger.warning("Error returned from %s during GET %s: %s", remote_url, jobid, err)
                return

            history = [ JobStepInfo.model_validate(trs) \
                        for trs in await resp.json() ]
            updated = await update_status(job, history)

            if updated or job.history[-1].state == JobState.active:
                # pull logs
                resp = await client.get(f"/v3/jobs/{jobid}/logs")
                if resp.status//100 != 2:
                    err = await resp.json()
                    _logger.warning("Error returned from %s during GET %s: %s", remote_url, jobid, err)
                    return
                logs = await resp.json()
                for lname, data in logs.items():
                    if "/" in lname:
                        _logger.error("Invalid logfile name returned: %s - skipping!", lname)
                        continue
                    if lname == "console":
                        lname = "console.1" # don't overrite our own console
                    elif lname.startswith("console."): # remap
                        n = int(lname[8:])
                        lname = f"console.{n+1}"
                    print(f"+ Updating {lname}: {len(data)} bytes")
                    with open(local_dir/"log"/lname, "w") as f:
                        f.write(data)

            if not updated:
                _logger.info("No state updates. Skipping file refresh.")

            if job.history[-1].state.is_final():
                _logger.error("Final file download not implemented.")
            #    await mirror_dir(machine, remote_dir/"work", local_dir/"work")
            #else:
            #    _logger.info("Job is not in final state. Skipping work dir download.")
    except Exception as err:
        _logger.error("Error connecting to %s: %s", remote_url, err)

