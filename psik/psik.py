import asyncio
from typing import Optional
from pathlib import Path
import logging
from typing_extensions import Annotated
import sys
_logger = logging.getLogger(__name__)

import typer

from .config import load_config
from .job import Job
from .manager import JobManager
from .models import JobSpec, ResourceSpec, JobAttributes, load_jobspec

def setup_logging(v, vv):
    if vv:
        logging.basicConfig(level=logging.DEBUG)
    elif v:
        logging.basicConfig(level=logging.INFO)

app = typer.Typer()

V1 = Annotated[bool, typer.Option("-v", help="show info-level logs")]
V2 = Annotated[bool, typer.Option("-vv", help="show debug-level logs")]
CfgArg = Annotated[Optional[Path], typer.Option("--config",
                   help="Config file path [default ~/.config/psik.json].")]

@app.command()
def status(stamp : str = typer.Argument(..., help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Read job status information and history.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = Path(config.prefix) / config.backend

    job = Job(base / str(stamp))
    #print(job.spec.dump_model_json(indent=4))
    print(job.spec.name)
    print()
    print("time ndx state info")
    for line in job.history:
        print("%.3f %3d %10s %8d" % line)

@app.command()
def cancel(stamp : str = typer.Argument(..., help="Job's timestamp / handle."),
           v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Cancel a job.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = Path(config.prefix) / config.backend

    job = Job(base / str(stamp))
    loop = asyncio.get_event_loop()
    loop.run_until_complete(job.cancel())

@app.command()
def reached(base : str = typer.Argument(..., help="Job's base directory."),
            jobndx : int = typer.Argument(..., help="Sequential job index."),
            state : str = typer.Argument(..., help="State reached by job."),
            info  : int = typer.Argument(default=0, help="Status code.")):
    """
    Record that a job has entered the given state.
    This script is typically not called by a user, but
    instead called during a job's (pre-filled) callbacks.
    """
    job = Job(base, read_info=False)
    job.reached(jobndx, state, info)

@app.command()
def ls(v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    List jobs.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
    base = Path(config.prefix) / config.backend

    mgr = JobManager(base, defaults = config.default_attr)
    for name, job in mgr.ls().items():
        t, ndx, state, info = job.history[-1]
        print(f"{name} {job.spec.name} {t} {ndx} {state} {info}")

@app.command()
def run(jobspec : str = typer.Argument(..., help="jobspec.json file to run"),
        test    : Annotated[bool, typer.Option(help="create scripts, but do not run")] = False,
        v : V1 = False, vv : V2 = False, cfg : CfgArg = None):
    """
    Run a job from a jobspec.json file.
    """
    setup_logging(v, vv)
    config = load_config(cfg)
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
