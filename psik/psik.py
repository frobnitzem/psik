import asyncio
from typing import Optional, List
from pathlib import Path
from typing_extensions import Annotated
import sys
import os
import shutil
import logging
_logger = logging.getLogger(__name__)

import typer

from .config import load_config
from .job import Job
from .manager import JobManager
from .models import (
        JobState,
        JobSpec,
        load_jobspec
)
from .exceptions import CallbackException

def run_async(f):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(f)

def setup_logging(v, vv):
    if vv:
        logging.basicConfig(level=logging.DEBUG)
    elif v:
        logging.basicConfig(level=logging.INFO)

app = typer.Typer()

V1 = Annotated[bool, typer.Option("-v", help="show info-level logs")]
V2 = Annotated[bool, typer.Option("-vv", help="show debug-level logs")]
CfgArg = Annotated[Optional[Path], typer.Option("--config",
                   envvar="PSIK_CONFIG",
                   help="Config file path [default ~/.config/psik.json].")]

@app.command()
def status(stamps: List[str] = typer.Argument(..., help="Job's timestamp / handle."),
           v: V1 = False, vv: V2 = False, cfg: CfgArg = None):
    """
    Read job status information and history.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    async def stat(stamp):
        job = await Job(base / stamp)
        #print(job.spec.dump_model_json(indent=4))
        print(job.spec.name)
        print("    base: %s"%str(base / stamp))
        print("    work: %s"%str(job.spec.directory))
        print()
        print("    time ndx state info")
        for line in job.history:
            print("    %.3f %3d %10s %8d" % (line.time, line.jobndx, line.state.value, line.info))

    async def loop_stat():
        for stamp in stamps:
            await stat(stamp)

    run_async(loop_stat())

@app.command()
def rm(stamps : List[str] = typer.Argument(...,
                                           help="Job's timestamp / handle."),
       cfg : CfgArg = None):
    """
    Remove job tracking directories for the given jobstamps.
    """
    config = load_config(cfg)
    base = config.prefix
    # TODO: Check with the backend and prevent deletion if
    # job is still there.

    err = 0
    for stamp in stamps:
        jobdir = base / str(stamp)
        if not jobdir.is_dir():
            _logger.error("%s not found", jobdir)
            err += 1
            continue
        if not os.access(jobdir, os.W_OK):
            _logger.error("%s no write permissions", jobdir)
            err += 1
            continue
        shutil.rmtree(jobdir)
        print(f"Deleted {stamp}")

    raise typer.Exit(code=err)

@app.command()
def start(stamp : str = typer.Argument(..., help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    (re)start a job.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    job = Job(base / str(stamp))
    run_async( job.submit() )
    print(f"Started {job.stamp}")

@app.command()
def hot_start(stamp: Annotated[str, typer.Argument(help="Job's timestamp / handle.")],
              jobndx: Annotated[int, typer.Argument(help="Sequential job index")],
              jobspec: Annotated[str, typer.Argument(help="Jobspec json")],
              backend: Annotated[str, typer.Option(help="Local backend used to template run-script")] = "default",
              v: V1 = False, vv : V2 = False,
              cfg : CfgArg = None):
    """
    (re)start a job directly into the "active" state.
    This method assumes resources are already allocated and
    we are inside a running "job-script".

    Hence, if the job dir. doesn't exist, it is created.
    If it does exist, reached(queued) and reached(active) are called
    in succession.
    """
    setup_logging(v, vv)
    config = load_config(cfg)

    try:
        spec = JobSpec.model_validate_json(jobspec)
    except Exception as e:
        _logger.exception("Error parsing JobSpec from cmd-line argument.")
        raise typer.Exit(code=1)

    spec.backend = backend

    async def do_hotstart():
        job = Job(config.prefix / str(stamp))
        if not await job.base.is_dir():
            # create if not available
            mgr = JobManager(config)
            job = await mgr.create(spec, job.base)
        else: # load
            job = await job

        ret, out, err = await runcmd(str(job.base / 'scripts' / 'run'), str(jobndx))
        # TODO: store this activity in the job's interaction log too.
        if ret != 0:
            raise SubmitException(err)

    run_async( do_hotstart() )

@app.command()
def cancel(stamp : str = typer.Argument(..., help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Cancel a job.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    job = Job(base / str(stamp))
    run_async( job.cancel() )
    print(f"Canceled {job.stamp}")

@app.command()
def reached(base : str = typer.Argument(..., help="Job's base directory."),
            jobndx : int = typer.Argument(..., help="Sequential job index."),
            state : JobState = typer.Argument(..., help="State reached by job."),
            info  : int = typer.Argument(default=0, help="Status code.")):
    """
    Record that a job has entered the given state.
    This script is typically not called by a user, but
    instead called during a job's (pre-filled) callbacks.
    """
    job = Job(base)
    try:
        ok = run_async( job.reached(jobndx, state, info) )
    except CallbackException as e:
        print("Error sending callback: ", str(e), file=sys.stderr)
        ok = False
    if not ok:
        raise typer.Exit(code=1)

@app.command()
def ls(stamps: List[str] = typer.Argument(None),
       v: V1 = False,
       vv: V2 = False,
       cfg: CfgArg = None):
    """
    List jobs.
    """
    if stamps:
        return status(stamps, v, vv, cfg)

    setup_logging(v, vv)
    config = load_config(cfg)
    mgr = JobManager(config)
    async def show():
        async for job in mgr.ls():
            t, ndx, state, info = job.history[-1]
            #print(f"{job.base} {job.spec.name} {t} {ndx} {state} {info}")
            print(f"{job.base} '{job.spec.name}' {state}/{ndx}")
    run_async(show())

@app.command()
def run(jobspec : str = typer.Argument(..., help="jobspec.json file to run"),
        submit  : Annotated[bool, typer.Option(help="Submit job to queue")] = True,
        v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Create a job directory from a jobspec.json file.

    If submit is True (default), the job will also be submitted
    to the backend's job queue.  Use --no-submit to prevent this.
    """

    setup_logging(v, vv)
    config = load_config(cfg)
    mgr = JobManager(config)
    try:
        spec = load_jobspec(jobspec)
    except Exception as e:
        _logger.exception("Error parsing JobSpec from file %s", jobspec)
        raise typer.Exit(code=1)

    async def create_submit(spec, submit):
        job = await mgr.create(spec)
        if submit:
            await job.submit()
        return job
        
    job = run_async( create_submit(spec, submit) )
    if submit:
        print(f"Queued {job.stamp}")
    else:
        print(f"Created {job.stamp}")
