from typing import List, Optional, Set, Tuple
import asyncio
import os
import sys
import json
from pathlib import Path
from shlex import quote
import logging
_logger = logging.getLogger(__name__)

from certified import Certified
import aiohttp

import psik
from ..job import Job
from ..config import Config
from ..models import (
    JobState,
    JobSpec,
    ExtraInfo,
    BackendConfig,
    Transition,
)
from ..console import runcmd
from ..zipstr import dir_to_str

from .slurm import mk_args

use_mtls = True

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    POST this jobspec to the API.

    Attributes:

      remote_url: URL of psik_api
      remote_backend: name of backend to use on remote side
      next: job.backend.attributes to forward to API

    TODO: use submit=False if there are files to send.
    """
    assert job.spec.directory is not None

    # job.info.backend.attributes["remote_url"] = remote URL
    # job.info.backend.attributes["remote_backend"] = remote backend

    # setup job for the remote site
    spec = job.spec.copy()

    remote_url = job.info.backend.attributes["remote_url"]
    try:
        spec.backend = job.info.backend.attributes["remote_backend"]
    except KeyError:
        spec.backend = "default"

    job.info = job.info.copy()
    job.info.backend = job.info.backend.copy()
    job.info.backend.attributes = job.info.backend.attributes.get("next", {})

    spec.directory = None
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        cert = Certified()
    else
        cert = aiohttp

    try:
        async with cert.ClientSession(
                        base_url=remote_url,
                        headers=headers
                    ) as client:
            #resp = await client.post("/v3/jobs", json=spec, params={"submit":False})
            resp = await client.post("/v3/jobs", json=spec)
            result = await resp.text()
            if resp.status_code//100 != 2:
                _logger.error("Error submitting job script to %s: %s", remote_url, result)
                return None
    except Exception as err:
        _logger.error("Error submitting job script to %s: %s", remote_url, err)
        return None

    return result


async def cancel(job: Job) -> None:
    jobinfos = await job.live_ids()
    remote_url = job.info.backend.attributes["remote_url"]
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        cert = Certified()
    else
        cert = aiohttp

    try:
        async with cert.ClientSession(
                        base_url=remote_url,
                        headers=headers
                    ) as client:
            for id in jobinfos:
                resp = await client.delete("/v3/jobs/{id}")
                if resp.status_code//100 != 2:
                    err = await resp.text()
                    _logger.warning("Error returned from %s during cancel %s: %s", remote_url, id, err)
    except Exception as err:
        _logger.error("Error connecting to %s: %s", remote_url, err)


async def update_status(job: Job, history: List[Transition]):
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
                          backdate=trs.time)

    return updated


async def poll(job: Job) -> None:
    remote_url = job.info.backend.attributes["remote_url"]
    headers = { "User-Agent": f"psik/{psik.__version__}",
                "Accept": "application/json" }

    mtls = use_mtls and remote_url.startswith("https")
    if mtls:
        cert = Certified()
    else
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
            resp = await client.get("/v3/jobs/{jobid}")
            if resp.status_code//100 != 2:
                err = await resp.text()
                _logger.warning("Error returned from %s during GET %s: %s", remote_url, jobid, err)
                return

            history = [ Transition.model_validate(trs) \
                        for trs in await resp.json() ]
            updated = await update_status(job, history)

            if updated or job.history[-1].state == JobState.active:
                # pull logs
                resp = await client.get("/v3/logs/{jobid}")
                if resp.status_code//100 != 2:
                    err = await resp.text()
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

