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
import yaml # type: ignore[import-untyped]

from .config import load_config
from .job import Job, runcmd
from .zipstr import str_to_dir
from .manager import JobManager
from .models import (
        JobState,
        JobSpec,
        load_jobspec
)
from .exceptions import CallbackException
from .logs import setup_log, logfile
from . import __version__

def run_async(f):
    #loop = asyncio.get_event_loop()
    #return loop.run_until_complete(f)
    return asyncio.run(f)

def setup_logging(v, vv):
    setup_log(True, v, vv)

app = typer.Typer()

V1 = Annotated[bool, typer.Option("-v", help="show info-level logs")]
V2 = Annotated[bool, typer.Option("-vv", help="show debug-level logs")]
CfgArg = Annotated[Optional[Path], typer.Option("--config",
                   envvar="PSIK_CONFIG",
                   help="Config file path [default ~/.config/psik.json].")]

@app.command()
def version():
    """
    Print psik's version and exit.
    """
    print(f"psik version {__version__}")

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
        print(f"{'jobid':<15} {'state':>10} jobndx info name")
        async for job in mgr.ls():
            #line.time, line.jobndx, line.state.value, line.info))
            h = job.history[-1]
            #print(f"{job.base} {job.spec.name} {h.time} {h.jobndx} {h.state.value} {h.info}")
            print(f"{job.stamp:<15} {h.state.value:<10} {h.jobndx:>6} {h.info:>4} {job.spec.name}")
    run_async(show())

async def stat(base, stamp):
    job = await Job(base / stamp)
    #print(job.spec.dump_model_json(indent=4))
    print(job.spec.name)
    print("    base: %s"%str(base / stamp))
    print("    work: %s"%str(job.spec.directory))
    print()
    print("    time ndx state info")
    for line in job.history:
        print("    %.3f %3d %10s %8s" % (line.time, line.jobndx, line.state.value, line.info))

@app.command()
def status(stamps: List[str] = typer.Argument(..., help="Job's timestamp / handle."),
           v: V1 = False, vv: V2 = False, cfg: CfgArg = None):
    """
    Read job status information and history.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    async def loop_stat():
        for stamp in stamps:
            await stat(base, stamp)

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
def submit(jobspec : str = typer.Argument(..., help="jobspec.json file to run"),
        submit  : Annotated[bool, typer.Option(help="Submit job to queue")] = True,
        here: Annotated[bool, typer.Option(help="Set spec.directory to the current working directory.")] = False,
        v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """ Synonym for run
    """
    run(jobspec, submit, here, v, vv, cfg)

@app.command()
def run(jobspec : str = typer.Argument(..., help="jobspec.json file to run"),
        submit  : Annotated[bool, typer.Option(help="Submit job to queue")] = True,
        here: Annotated[bool, typer.Option(help="Set spec.directory to the current working directory.")] = False,
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
    if here: # run in current working dir.
        cwd = str(Path().resolve())
        if spec.directory is not None:
            _logger.warning("Overriding spec.directory to %s", cwd)
        spec.directory = cwd

    async def create_submit(spec, submit):
        job = await mgr.create(spec)
        with logfile(str(job.base/'log'/'console'), v=v, vv=vv):
            if submit:
                try:
                    await job.submit()
                except Exception as e:
                    _logger.exception("Error submitting job")
                    print(f"Created {job.stamp}")
                    exit(1)
            return job
        
    job = run_async( create_submit(spec, submit) )
    if submit:
        print(f"Queued {job.stamp}")
    else:
        print(f"Created {job.stamp}")

@app.command()
def start(stamps : List[str] = typer.Argument(...,
                                           help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    (re)start a job.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    for stamp in stamps:
        job = Job(base / str(stamp))
        with logfile(str(job.base/'log'/'console'), v=v, vv=vv):
            run_async( job.submit() )
            print(f"Started {job.stamp}")

@app.command()
def poll(stamps : List[str] = typer.Argument(...,
                                          help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Poll a job's state, retrieving any updates.

    Hint: This action can be triggered by receiving
          a callback (notification of a state change)
          from the job itself.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    for stamp in stamps:
        job = Job(base / str(stamp))
        with logfile(str(job.base/'log'/'console'), v=v, vv=vv):
            run_async( job.poll() )
        run_async( stat(base, stamp) )

@app.command()
def cancel(stamps : List[str] = typer.Argument(...,
                                           help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Cancel a job.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = config.prefix

    for stamp in stamps:
        job = Job(base / str(stamp))
        with logfile(str(job.base/'log'/'console'), v=v, vv=vv):
            run_async( job.cancel() )
            print(f"Canceled {job.stamp}")

@app.command()
def reached(base : str = typer.Argument(..., help="Job's base directory."),
            jobndx : int = typer.Argument(..., help="Sequential job index."),
            state : JobState = typer.Argument(..., help="State reached by job."),
            info  : str = typer.Argument(default="", help="Status info.")):
    """
    Record that a job has entered the given state.
    This script is typically not called by a user, but
    instead called during a job's (pre-filled) callbacks.
    """
    job = Job(base)
    with logfile(str(job.base/'log'/'console')):
        try:
            ok = run_async( job.reached(jobndx, state, info) )
        except CallbackException as e:
            _logger.error("Error sending callback: %s", e)
            ok = False

    if not ok:
        raise typer.Exit(code=1)

@app.command()
def hot_start(stamp: Annotated[str, typer.Argument(help="Job's timestamp / handle.")],
              jobndx: Annotated[int, typer.Argument(help="Sequential job index")],
              jobspec: Annotated[str, typer.Argument(help="Jobspec json")],
              zstr: Annotated[Optional[str], typer.Argument(help="b64-encoded zipfile to unpack into job dir")] = None,
              v: V1 = False, vv : V2 = False,
              cfg : CfgArg = None):
    """
    (re)start a job directly into the "active" state.
    This method assumes resources are already allocated and
    we are inside a running "job-script".

    Hence, if the job dir. doesn't exist, it is created.
    If zstr is provided, it is decoded and unpacked into
    the job's working directory.

    This program changes to the job's working directory,
    calls reached(queued), then runs the `scripts/job` script
    synchronously, returning only when it exits.  Note
    that `job` itself runs the reached(active) and
    reached(complete/failed) calls.
    """
    setup_logging(v, vv)
    config = load_config(cfg)

    try:
        spec = JobSpec.model_validate_json(jobspec)
    except Exception as e:
        _logger.exception("Error parsing JobSpec from cmd-line argument.")
        raise typer.Exit(code=1)

    async def do_hotstart() -> int:
        job = Job(config.prefix / str(stamp))
        if not await job.base.is_dir() or \
                not await (job.base/'spec.json').exists():
            await job.base.mkdir(exist_ok=True, parents=True)
            # Ensure working directory exists.
            if spec.directory is None:
                workdir = job.base / 'work'
                await workdir.mkdir()
                spec.directory = str(workdir)
            # create if not available
            mgr = JobManager(config)
            job = await mgr.create(spec, job.base)
        else: # load
            job = await job

        assert job.spec.directory is not None
        with logfile(str(job.base/'log'/'console'), v=v, vv=vv):
            os.chdir(job.spec.directory)
            if zstr is not None:
                str_to_dir(zstr, job.spec.directory)
            return await job.execute(jobndx)

    sys.exit(run_async( do_hotstart() ))
