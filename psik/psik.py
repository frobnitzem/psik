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
def status(stamp : str = typer.Argument(..., help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Read job status information and history.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    async def stat():
        job = await Job(base / stamp)
        #print(job.spec.dump_model_json(indent=4))
        print(job.spec.name)
        print("    base: %s"%str(base / stamp))
        print("    work: %s"%str(job.spec.directory))
        print()
        print("    time ndx state info")
        for line in job.history:
            print("    %.3f %3d %10s %8d" % line)
    run_async(stat())

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

    raise typer.Exit(code=err)

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
    ok = run_async( job.reached(jobndx, state, info) )
    if not ok:
        raise typer.Exit(code=1)

@app.command()
def ls(v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    List jobs.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    mgr = JobManager(config)
    async def show():
        async for job in mgr.ls():
            t, ndx, state, info = job.history[-1]
            print(f"{job.stamp} {job.spec.name} {t} {ndx} {state} {info}")
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
        
    run_async( create_submit(spec, submit) )
