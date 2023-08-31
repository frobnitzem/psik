import asyncio
from typing import Optional
from pathlib import Path
import logging
import sys
_logger = logging.getLogger(__name__)

import typer

from .config import load_config
from .job import JobManager
from .models import JobSpec, ResourceSpec, JobAttributes, load_jobspec

def setup_logging(v, vv):
    if vv:
        logging.basicConfig(level=logging.DEBUG)
    elif v:
        logging.basicConfig(level=logging.INFO)

async def run_in_loop(w, timeout=None):
    async with EventLoop(timeout) as ev:
        ev.start(w)

app = typer.Typer()

@app.command()
def status(job : str = typer.Argument(..., help="Job's timestamp / handle."),
        v : bool = typer.Option(False, "-v", help="show info-level logs"),
        vv : bool = typer.Option(False, "-vv", help="show debug-level logs"),
        config : Optional[Path] = typer.Option(None, help="Config file path [default ~/.config/psik.json].")):
    """
    Read job status information and history.
    """
    setup_logging(v, vv)
    config = load_config(config)
    base = Path(config.prefix) / config.backend

    job = Job(base / str(job))
    #print(job.spec.dump_model_json(indent=4))
    print(job.spec.name)
    print()
    print("time state info")
    for line in job.history:
        print("%.3f %10s %d" % line)

@app.command()
def cancel(job : str = typer.Argument(..., help="Job's timestamp / handle."),
        v : bool = typer.Option(False, "-v", help="show info-level logs"),
        vv : bool = typer.Option(False, "-vv", help="show debug-level logs"),
        config : Optional[Path] = typer.Option(None, help="Config file path [default ~/.config/psik.json].")):
    """
    Cancel a job.
    """
    setup_logging(v, vv)
    config = load_config(config)
    base = Path(config.prefix) / config.backend

    job = Job(base / str(job))
    job.cancel()

@app.command()
def reached(base : str = typer.Argument(..., help="Job's base directory."),
            jobidx : int = typer.Argument(..., help="Sequential job index."),
            state : str = typer.Argument(..., help="State reached by job."),
            info  : int = typer.Argument(0, help="Status code.")):
    """
    Record that a job has entered the given state.
    This script is typically not called by a user, but
    instead called during a job's (pre-filled) callbacks.
    """
    job = Job(base, read_info=False)
    job.reached(jobidx, state, info)

@app.command()
def ls( v : bool = typer.Option(False, "-v", help="show info-level logs"),
        vv : bool = typer.Option(False, "-vv", help="show debug-level logs"),
        config : Optional[Path] = typer.Option(None, help="Config file path [default ~/.config/psik.json].")):
    """
    List jobs.
    """
    setup_logging(v, vv)
    config = load_config(config)
    base = Path(config.prefix) / config.backend

    mgr = JobManager(base, defaults = config.default_attr)
    for name, info in mgr.ls().items():
        print(f"# {name}, {info.name}")
        print()
        print("    time state info")
        for line in job.history:
            print("    %f %s %d" % line)

@app.command()
def run(jobspec : str = typer.Argument(..., help="jobspec.json file to run"),
        test    : bool = typer.Option(False, help="create scripts, but do not run"),
        v       : bool = typer.Option(False, "-v", help="show info-level logs"),
        vv      : bool = typer.Option(False, "-vv", help="show debug-level logs"),
        config  : Optional[Path] = typer.Option(None, help="Config file path [default ~/.config/psik.json].")):
    """
    Run a job from a jobspec.json file.
    """
    setup_logging(v, vv)
    config = load_config(config)
    base = Path(config.prefix) / config.backend

    mgr = JobManager(base, defaults = config.default_attr)
    try:
        spec = load_jobspec(jobspec)
    except Exception as e:
        print(f"Error parsing JobSpec from file {jobspec}:")
        print(e)
        sys.exit(1)

    job = mgr.create(spec)
    if not test:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(job.submit())
