from typing import List, Optional, Set, Tuple
import asyncio
import os
import sys
import json
from pathlib import Path
import logging
_logger = logging.getLogger(__name__)

from sfapi_client import AsyncClient, SfApiError # type: ignore[import-untyped]
from sfapi_client.compute import Machine, AsyncCompute # type: ignore[import-untyped]

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

slurm_script = """#!/bin/bash
%(slurm_opts)s

if ! [ -x %(venv)s/bin/psik ]; then
    if ! which uv; then
        echo "Installing uv"
        if which curl; then
            curl -LsSf https://astral.sh/uv/install.sh | sh
        else
            if which wget; then
                wget -qO- https://astral.sh/uv/install.sh | sh
            else
                echo "No curl or wget."
                exit 1
            fi
        fi
    fi

    echo "Installing psik to %(venv)s"
    uv venv --no-project --managed-python --python 3.12 %(venv)s
    uv pip install --python %(venv)s/bin/python certified aiohttp psik libenv
    mkdir -p %(venv)s/etc
    cat >%(venv)s/etc/psik.json <<__EOF__
%(config)s
__EOF__
    # TODO: install client cert.
fi

export VIRTUAL_ENV="%(venv)s"
export nodes=$SLURM_JOB_NUM_NODES
export jobid=$SLURM_JOB_ID
export mpirun=srun
# use exec to forward signals properly
exec %(venv)s/bin/psik hot-start %(stamp)s %(jobndx)d '%(jobspec)s' '%(zstr)s'
"""

def quote(s: str) -> str:
    return s

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    Create a templated run-script and send it
    to NERSC's SFAPI.
    """
    assert job.spec.directory is not None
    args = mk_args(job.spec, job.info)
    if len(args) > 0:
        slurm_opts = "#SBATCH %s"%(" ".join(args))
    else:
        slurm_opts = ""

    # TODO: gather settings from job.info.backend.attributes
    remote_prefix = "$HOME/psik"
    remote_config = Config(prefix=Path(remote_prefix),
                           backends={
                               job.spec.backend: BackendConfig()
                           })
    machine_id = Machine["perlmutter"]
    remote_venv = "$HOME/venv"

    jspec = job.spec.copy()
    jspec.directory = None
    spec = jspec.model_dump_json()
    cfg = remote_config.model_dump_json(indent=2)
    # zip up the contents of the working dir.
    zstr = dir_to_str(job.spec.directory)
    jobscript = slurm_script % dict(
        slurm_opts = slurm_opts,
        venv = remote_venv,
        config = cfg,
        stamp = job.stamp,
        jobspec = quote(spec),
        jobndx = jobndx,
        zstr = zstr,
    )

    keypath = Path(os.environ["HOME"]) / ".superfacility" / "key.pem"
    _logger.debug("Submitting job script to NERSC: %s", jobscript)
    # Note: beware the dreaded {"detail":"Not authenticated"}
    try:
        async with AsyncClient(key=keypath) as client:
            #user = await client.user()
            #user_name = user.name
            #user_home = f'/global/homes/{user_name[0]}/{user_name}'
            machine = await client.compute(machine_id)
            njob = await machine.submit_job(jobscript)
            result = njob.jobid
    except Exception as err:
        _logger.error("Error submitting job script to sbatch: %s", err)
        return None

    return result

async def cancel(jobinfos: List[str]) -> None:
    machine_id = Machine["perlmutter"]

    keypath = Path(os.environ["HOME"]) / ".superfacility" / "key.pem"
    try:
        async with AsyncClient(key=keypath) as client:
            machine = await client.compute(machine_id)
            jobs = await machine.jobs(jobids=jobinfos)
            for job in jobs:
                _logger.info("Canceling %s (%s)", job.jobid, job.state)
                await job.cancel()
    except Exception as err:
        _logger.error("Error canceling job(s): %s", err)

async def mirror_dir(machine: AsyncCompute,
                     remote_dir: Path,
                     local_dir: Path) -> None:
    _logger.info(f"Mirroring files: %s -> %s", remote_dir, local_dir)
    for f in await machine.ls(str(remote_dir)):
        if await f.is_file():
            _logger.info(f.perms, f.hardlinks, f.user, f.group, f.size, f.date, f.name)
            # Write the BytesIO content to a file
            #rel_path(remote_dir, f.name)
            if f.name.startswith("/"):
                _logger.error("Error: file name (%s) should be relative.", f.name)
                continue
            local = local_dir/f.name
            if local.exists():
                st = local.stat()
                if st.st_size == f.size and st.st_mtime >= f.date:
                    _logger.info("    - Skipping.")
                    continue
                else:
                    _logger.info("    - Re-downloading.")
            else:
                _logger.info("    - Downloading.")
            fio = await f.download()
            with open(local_dir/f.name, "wb") as outfile:
                outfile.write(fio.getbuffer())

async def poll(job: Job) -> None:
    machine_id = Machine["perlmutter"]

    keypath = Path(os.environ["HOME"]) / ".superfacility" / "key.pem"
    _logger.debug("Polling job on NERSC.")
    # Note: beware the dreaded {"detail":"Not authenticated"}
    try:
        async with AsyncClient(key=keypath) as client:
            user = await client.user()
            user_name = user.name
            user_home = Path(f"/global/homes/{user_name[0]}/{user_name}")
            psik_prefix = user_home / "psik"
            # TODO: allow job.info.backend to customize psik_prefix

            local_dir = Path(job.base)
            remote_dir = psik_prefix / job.stamp

            machine: AsyncCompute = await client.compute(machine_id)

            try:
                status_l = await machine.ls(str(remote_dir/"status.csv"))
            except SfApiError:
                status_l = []

            if not (len(status_l) == 1 and await status_l[0].is_file()):
                _logger.info("Job has not been created on remote.")
                return None
            history = [ line.strip().split(',', 3) for line in (
                            await status_l[0].download()
                        ).read().decode("utf-8").split("\n")
                      ]
            # filter events we have seen
            events: Set[Tuple[int,JobState]] = set()
            for trs in job.history:
                events.add( (trs.jobndx, trs.state) )

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
                    continue
                events.add(key)
                await job.reached(trs.jobndx, trs.state, trs.info,
                                  backdate=trs.time)

            await mirror_dir(machine, remote_dir/"log", local_dir/"log")
            if job.history[-1].state.is_final():
                await mirror_dir(machine, remote_dir/"work", local_dir/"work")
            else:
                _logger.info("Job is not in final state. Skipping work dir download.")
    except Exception as err:
        _logger.error("Error submitting job script to sbatch: %s", err)
