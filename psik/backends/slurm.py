import asyncio
from typing import List, Optional
import os
import sys
import logging
_logger = logging.getLogger(__name__)

from psik import Job, JobState, JobSpec
from psik.models import ExtraInfo
from psik.console import runcmd

slurm_script = """#!%(psik_python)s
#SBATCH -e %(base)s/log/console
#SBATCH -o %(base)s/log/console

import asyncio
import psik

# determine helpful env variables
nodes = os.environ.get("SLURM_JOB_NUM_NODES", 1)
jobid = os.environ.get("SLURM_JOB_ID", "-1")
# nodelist = ...

async def main():
    job = await psik.Job("%(base)s")
    await job.execute(%(jobndx)d,
                      jobid=jobid,
                      mpirun="srun",
                      nodes=nodes)

asyncio.run(main())
"""

def mk_args(spec: JobSpec, extra: ExtraInfo) -> List[str]:
    assert spec.directory is not None
    args: List[str] = []

    if spec.name:
        args.extend(["--job-name", spec.name])
    # Interferes with remote launch. Done inside exec anyway.
    #args.extend(["--chdir", spec.directory])
    if spec.inherit_environment:
        args.extend(["--export", "ALL"])
    else:
        args.extend(["--export", "NONE"])
    rec = spec.resources
    if rec.duration:
        args.extend(["--time", str(rec.duration)])
    if rec.node_count:
        args.extend(["--nodes", str(rec.node_count)])
    if rec.process_count:
        args.extend(["--ntasks", str(rec.process_count)])
    if rec.processes_per_node:
        args.extend(["--ntasks-per-node", str(rec.processes_per_node)])
    if rec.gpu_cores_per_process:
        args.extend(["--gpus-per-task", str(rec.gpu_cores_per_process)])

    # SLURM has different meanings for 'CPU', depending on the
    # exact allocation plugin being used. The default plugin
    # uses the literal meaning for 'CPU' - physical processor. The
    # consumable resource allocation plugin, on the other hand,
    # equates 'CPU' to a thread (if hyperthreaded CPUs are used)
    # or CPU core (for non-hyperthreaded CPUs).
    if rec.cpu_cores_per_process:
        args.extend(["--cpus-per-task", str(rec.cpu_cores_per_process)])
    if rec.exclusive_node_use:
        args.extend(["--exclusive"])

    if extra.backend.queue_name:
        args.extend(["--partition", extra.backend.queue_name])
    if extra.backend.project_name:
        args.extend(["--account", extra.backend.project_name])
    for key, value in spec.attributes.items():
        args.extend([key, value])
    return args

async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    Create a templated run-script and execute it
    via SLURM.
    """
    jobscript = slurm_script % dict(
        psik_python = sys.executable,
        base = job.base,
        jobndx = jobndx,
    )
    args = mk_args(job.spec, job.info)

    _logger.debug("Submitting job script to sbatch: %s", " ".join(map(str,args)))
    ret, out, err = await runcmd("sbatch", *args,
                                 stdin = jobscript)
    if ret != 0:
        _logger.error("Error submitting job script to sbatch: %s", err)
        return None
    _logger.debug("sbatch result: %s", out)

    # printed output matches
    # Submitted batch job 1431123
    return out.split()[-1]

async def poll(job: Job) -> None:
    return None

async def cancel(jobinfos: List[str]) -> None:
    ret, out, err = await runcmd("scancel", *jobinfos)
    return None
