from typing import List, Optional, Set, Tuple
import asyncio
import os
import sys
import time
import json
from pathlib import Path
import logging
_logger = logging.getLogger(__name__)

from globus_compute_sdk import Client, Executor, ShellFunction

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
from ..zipstr import dir_to_str, str_to_dir

def send_prefix(backend: BackendConfig) -> str:
    """ Read the remote's prefix from backend.project_name.
        Default to "%FIXME%" if unset.
    """
    return backend.project_name if backend.project_name \
                                else "%FIXME%"

def remote_prefix(pre: str) -> Path:
    """ Correct the remote prefix path (handling the unset, FIXME case)
    """
    import os
    from pathlib import Path
    if pre != "%FIXME%":
        return Path(pre)

    home = Path()
    if "HOME" in os.environ:
        home = Path(os.environ["HOME"])
    return home/"psik_jobs"

def remote_submit(cfg: str,
                  stamp: str,
                  jobspec: str,
                  zstr: Optional[str] = None):
    """ Function to run on the remote side which will submit the
        psik jobspec.

        params:
         - config - psik.Config to use on the remote side.
         - stamp - job's stamp (will be same on local and remote)
         - spec - jobspec (has been customized for remote side)
         - zstr - zipped string of work directory contents
    """
    import asyncio
    import os
    import psik
    from psik.logs import logfile

    config = psik.Config.model_validate_json(cfg)
    config.prefix = remote_prefix(str(config.prefix))
    mgr = psik.JobManager(config)

    spec = psik.JobSpec.model_validate_json(jobspec)

    async def submit_job():
        job = psik.Job(prefix / stamp)
        await job.base.mkdir(exist_ok=True, parents=True)
        # Ensure working directory exists.
        if spec.directory is None: # should always be True
            workdir = job.base / 'work'
            await workdir.mkdir(exist_ok=True)
            spec.directory = str(workdir)

        # create if not available
        if await (job.base/'spec.json').exists():
            job = await job
        else:
            job = await mgr.create(spec, job.base)
        with logfile(str(job.base/'log'/'console'), v=True, vv=False):
            if zstr is not None:
                psik.zipstr.str_to_dir(zstr, spec.directory)
            return await job.submit()

    return asyncio.run(submit_job())

def remote_cancel(rprefix: str, stamp: str):
    import asyncio
    from psik import Job
    from psik.logs import logfile

    prefix = remote_prefix(rprefix)
    job = Job(prefix / stamp)
    with logfile(str(job.base/'log'/'console'), v=True, vv=False):
        asyncio.run( job.cancel() )

def remote_poll(rprefix: str, stamp: str) -> Tuple[str,str,str]:
    import asyncio
    from psik.zipstr import dir_to_str

    prefix = remote_prefix(rprefix)
    base = prefix/stamp
    #job = asyncio.run( Job(prefix / stamp) )
    hist = (base/"status.csv").read_text()
    logs = dir_to_str(str(base/"log"))
    data = dir_to_str(str(base/"work"))

    return hist, logs, data

def send_config(bname: str, backend: BackendConfig) -> Config:
    return Config(prefix = Path(send_prefix(backend)),
                  backends = { bname: BackendConfig.model_validate(
                                                    backend.attributes)
                             }
                 )

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    Submit job to the remote host.  Globus serializes
    job.spec for us, so we can execute job.submit remotely.
    """
    assert job.spec.directory is not None
    backend = job.info.backend

    jspec = job.spec.copy()
    jspec.directory = None

    # Use project_name as psik prefix (if present)
    remote_config = send_config(job.spec.backend, backend)
    #cfg = remote_config.model_dump_json(indent=2)

    #spec = jspec.model_dump_json()
    # zip up the contents of the working dir.
    zstr = dir_to_str(job.spec.directory)

    #_logger.debug("Submitting job to globus: %s", jobscript)
    #if os.getenv("GLOBUS_COMPUTE_CLIENT_ID") is None:
    #    raise ValueError("GLOBUS_COMPUTE_CLIENT_ID env var must be defined")
    #if os.getenv("GLOBUS_COMPUTE_CLIENT_SECRET") is None:
    #    raise ValueError("GLOBUS_COMPUTE_CLIENT_SECRET env var must be defined")
    try:
        gclient = Client()
        with Executor( endpoint_id = backend.queue_name
                     , client = gclient
                     ) as gce:
            future = gce.submit(remote_submit,
                    remote_config.model_dump_json(),
                    job.stamp,
                    jspec.model_dump_json(),
                    zstr)
            _logger.info("Submitted job to globus")
            result = future.result()
    except Exception as err:
        _logger.error("Error submitting job to globus: %s", err)
        return None

    return result

async def cancel(job: Job) -> None:
    if not job.valid:
        await job.read_info()

    backend = job.info.backend
    rprefix = send_prefix(backend)
    try:
        gclient = Client()
        with Executor( endpoint_id = backend.queue_name
                     , client = gclient
                     ) as gce:
            future = gce.submit(remote_cancel, rprefix, job.stamp)
            _logger.info("Canceling %s", job.stamp)
            result = future.result()
    except Exception as err:
        _logger.error("Error canceling job %s: %s", job.stamp, err)

async def poll(job: Job) -> None:
    jobid = "" # Determine jobid for last queued jobndx
    jobndx = 0
    for trs in job.history:
        if trs.state == JobState.queued:
            jobid = trs.info
            jobndx = trs.jobndx
    if jobid == "":
        raise ValueError("Job has not been queued.")
    assert job.spec.directory is not None, "Invalid job.spec"

    _logger.debug("Polling globus job.")
    backend = job.info.backend
    rprefix = send_prefix(backend)
    try:
        # TODO: read job.spec to create remote_config
        gclient = Client()
        with Executor( endpoint_id = backend.queue_name
                     , client = gclient
                     ) as gce:
            future = gce.submit(remote_poll, rprefix, job.stamp)
            _logger.info("Canceling")
            hist, logs, data = future.result()
    except Exception as err:
        _logger.error("Error polling job %s: %s", job.stamp, err)

    str_to_dir(data, job.spec.directory)
    local_dir = Path(job.base)

    history = [ line.strip().split(',', 3) for line in hist.split('\n') ]
    # filter events we have seen
    events: Set[Tuple[int,JobState]] = set()
    for trs in job.history:
        events.add( (trs.jobndx, trs.state) )

    updated = False
    for step in history:
        try:
            trs = Transition(time=float(step[0]),
                             jobndx=int(step[1]),
                             state=JobState(step[2]),
                             info=str(step[3]))
        except Exception as e:
            print("Invalid row in status.csv: %s"%step)
            continue
        key = (trs.jobndx, trs.state)
        if key in events: # we already know about this transition
            print(f"x {trs}")
            continue
        updated = True
        print(f"- {trs}")
        events.add(key)
        await job.reached(trs.jobndx, trs.state, trs.info,
                          backdate=trs.time)

    if not updated:
        _logger.info("No state updates. Skipping file refresh.")
        return
    # FIXME: rename remote console to console.1 locally
    str_to_dir(logs, str(local_dir/"log.1"))
    # FIXME: only retrieve data if state.is_final()
    if job.history[-1].state.is_final():
        str_to_dir(data, job.spec.directory)
    else:
        _logger.info("Job is not in final state. Skipping work dir download.")
