"""
IRI Facility API backend for psik.

This backend submits jobs to HPC facilities via the IRI API
(https://api.iri.nersc.gov).

Authentication uses Globus Auth tokens with the scope:
https://auth.globus.org/scopes/ed3e577d-f7f3-4639-b96e-ff5a8445d699/iri_api

Backend configuration attributes:
- api_url: Base URL for the IRI API (default: https://api.iri.nersc.gov)
- resource_id: The resource ID to submit jobs to (e.g., "perlmutter")
- token: Globus access token (can also be set via IRI_TOKEN env var)
"""

from typing import Optional
import os
from pathlib import Path
from contextlib import asynccontextmanager
import urllib
from shlex import quote

import logging
_logger = logging.getLogger(__name__)

import aiohttp

from ..job import Job
from ..models import JobState, BackendConfig
from ..config import Config
from ..zipstr import dir_to_str


#export UV_TOOL_DIR="$SCRATCH/uv"
#export UV_CACHE_DIR="$SCRATCH/uv_cache"
#   if ! which uv; then
#       echo "Installing uv";
#       if which curl; then
#           curl -LsSf https://astral.sh/uv/install.sh | sh;
#       else
#           if which wget; then
#               wget -qO- https://astral.sh/uv/install.sh | sh;
#           else
#               echo "No curl or wget.";
#               exit 1;
#           fi
#       fi
#   fi
#   #echo "Installing psik to %(venv)s"
#   #uv venv --no-project --managed-python --python 3.12 "%(venv)s"
#   #uv pip install --python "%(venv)s/bin/python" certified aiohttp psik libenv

launch_script = """
export https_proxy=http://proxy.ccs.ornl.gov:3128/

if ! [ -x "%(venv)s/bin/psik" ]; then
    python3.11 -m venv "%(venv)s"
    %(venv)s/bin/pip install certified aiohttp libenv git+https://github.com/frobnitzem/psik
    mkdir -p "%(venv)s/etc"
    cat >"%(venv)s/etc/psik.json" <<__EOF__
%(config)s
__EOF__
    # TODO: install client cert.
fi

export nodes=$SLURM_JOB_NUM_NODES
export jobid=$SLURM_JOB_ID
export mpirun=srun
# use exec to forward signals properly
exec "%(venv)s/bin/psik" hot-start --config %(venv)s/etc/psik.json %(stamp)s %(jobndx)d %(jobspec)s %(zstr)s
"""

def encapsulated_script(job: Job, jobndx: int) -> str:
    """ Create and return an encapsulated jobscript that
        1. installs psik if needed
        2. hot-starts the current jobspec
    """
    assert job.spec.directory is not None

    # TODO: gather settings from job.info.backend.attributes
    remote_prefix = "$HOME/psik"
    remote_config = Config(prefix=Path(remote_prefix),
                           backends={
                               job.spec.backend: BackendConfig()
                           })
    remote_venv = "$HOME/venv"

    jspec = job.spec.copy()
    jspec.directory = None
    spec = jspec.model_dump_json()
    cfg = remote_config.model_dump_json(indent=2)
    # zip up the contents of the working dir.
    zstr = dir_to_str(job.spec.directory)
    jobscript = launch_script % dict(
        venv = remote_venv,
        config = cfg,
        stamp = job.stamp,
        jobspec = quote(spec),
        jobndx = jobndx,
        zstr = quote(zstr),
    )
    return jobscript

# Map IRI job states to psik JobState
IRI_STATE_MAP = {
    "QUEUED": JobState.queued,
    "PENDING": JobState.queued,
    "RUNNING": JobState.active,
    "COMPLETED": JobState.completed,
    "FAILED": JobState.failed,
    "CANCELLED": JobState.canceled,
    "CANCELED": JobState.canceled,
}


def get_api_config(backend: BackendConfig) -> tuple[str, str, str]:
    """Extract API URL, resource_id, and token from job config."""
    api_url = backend.attributes.get(
        "api_url", "https://api.iri.nersc.gov"
    )
    resource_id = backend.attributes.get("resource_id", "")
    if not resource_id:
        raise ValueError("Backend attribute 'resource_id' is required for IRI backend")
    
    # Token can come from config or environment
    tok_var = backend.attributes.get("token", "$IRI_TOKEN")
    if len(tok_var) < 2 or tok_var[0] != "$":
        raise ValueError(
            "'token' in backend config must be a variable name (e.g. $TOKEN)"
        )
    token = os.environ.get(tok_var[1:])
    if not token:
        raise ValueError(
            f"IRI API token required, but {tok_var} is not set"
        )
    
    return api_url, resource_id, token


def build_iri_jobspec(job: Job, jobndx: int) -> dict:  # type: ignore[type-arg]
    """Convert psik JobSpec to IRI JobSpec format."""
    spec = job.spec
    resources = spec.resources
    
    # Build IRI ResourceSpec
    resource_spec: dict = {}  # type: ignore[type-arg]
    if resources.node_count:
        resource_spec["node_count"] = resources.node_count
    elif resources.process_count and resources.processes_per_node:
        a = resources.process_count # compute using PPN, round up
        b = resources.processes_per_node
        resource_spec["node_count"] = (a+b-1)//b
    else: # ensure it's always set
        resource_spec["node_count"] = 1
    if resources.process_count:
        resource_spec["process_count"] = resources.process_count
    if resources.processes_per_node:
        resource_spec["processes_per_node"] = resources.processes_per_node
    if resources.cpu_cores_per_process:
        resource_spec["cpu_cores_per_process"] = resources.cpu_cores_per_process
    if resources.gpu_cores_per_process:
        resource_spec["gpu_cores_per_process"] = resources.gpu_cores_per_process
    resource_spec["exclusive_node_use"] = resources.exclusive_node_use
    
    # Build IRI JobAttributes
    job_attributes: dict = {}  # type: ignore[type-arg]
    job_attributes["duration"] = resources.duration * 60  # Convert minutes to seconds
    if job.info.backend.queue_name:
        job_attributes["queue_name"] = job.info.backend.queue_name
    if job.info.backend.project_name:
        job_attributes["account"] = job.info.backend.project_name
    if job.info.backend.reservation_id:
        job_attributes["reservation_id"] = job.info.backend.reservation_id
    
    # Merge custom attributes
    if spec.attributes:
        job_attributes["custom_attributes"] = spec.attributes
    
    # Build IRI JobSpec
    iri_spec: dict = {  # type: ignore[type-arg]
        "executable": "/bin/bash",
        "arguments": ["-c", encapsulated_script(job, jobndx)],
    }
    
    if spec.name:
        iri_spec["name"] = spec.name
    #if spec.directory:
    #    iri_spec["directory"] = spec.directory
    iri_spec["directory"] = "/tmp"
    if spec.environment:
        iri_spec["environment"] = spec.environment
    if not spec.inherit_environment:
        iri_spec["inherit_environment"] = False
    if resource_spec:
        iri_spec["resources"] = resource_spec
    if job_attributes:
        iri_spec["attributes"] = job_attributes
    
    return iri_spec


async def submit(job: Job, jobndx: int) -> Optional[str]:
    """
    Submit a job to the IRI API.
    
    Returns the job ID on success, None on failure.
    """
    # Build the IRI JobSpec
    iri_spec = build_iri_jobspec(job, jobndx)
    
    # Submit the job
    
    try:
        async with iri_session(job.info.backend) as (session, resource_id):
            url = f"/api/v1/compute/job/{resource_id}"
            _logger.debug("Submitting job to IRI API: %s", url)
            _logger.debug("Job spec: %s", iri_spec)
            async with session.post(url, json=iri_spec) as resp:
                if resp.status not in (200, 201):
                    #error_info = await resp.json() # error_info.detail
                    error_text = await resp.text()
                    _logger.error(
                        "Failed to submit job to IRI API (status %d): %s",
                        resp.status,
                        error_text
                    )
                    return None
                
                result = await resp.json()
                job_id = result.get("id")
                if not job_id:
                    _logger.error("IRI API response missing 'id' field: %s", result)
                    return None
                
                _logger.info("Job submitted successfully with ID: %s", job_id)
                return job_id
    except Exception as e:
        _logger.error("Error connecting to IRI API: %s", e)
        return None

async def download_file(session: aiohttp.ClientSession,
                        resource_id: str, path: str) -> bytes:
    quoted_path = urllib.parse.quote(path)
    url = f"/api/v1/filesystem/download/{resource_id}?path={quoted_path}"

    _logger.debug("Downloading file from IRI API: %s", url)
    async with session.get(url) as resp:
        if resp.status not in (200, 201):
            #error_info = await resp.json() # error_info.detail
            error_text = await resp.text()
            _logger.error(
                "Failed to download file from IRI API (status %d): %s",
                resp.status,
                error_text
            )
            return None

        result = await resp.json()
        task_id = str(result.get("task_id"))
        if not task_id:
            _logger.error("IRI API response missing 'task_id' field: %s", result)
            return None
        _logger.debug("Download returned: task_id %s", task_id)

    url = f"/api/v1/task/{task_id}"
    async with session.get(url) as resp:
        if resp.status not in (200, 201):
            #error_info = await resp.json() # error_info.detail
            error_text = await resp.text()
            _logger.error(
                "Failed to download file from IRI API (status %d): %s",
                resp.status,
                error_text
            )
            return None

        result = await resp.json()
        print(result)

@asynccontextmanager
async def iri_session(backend: BackendConfig):
    api_url, resource_id, token = get_api_config(backend)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(base_url=api_url, headers=headers) \
                as session:
        yield session, resource_id

async def poll(job: Job) -> None:
    """
    Poll the IRI API for job status and update local state.
    """
    # Find the most recent queued job
    jobid = ""
    jobndx = 0
    for trs in job.history:
        if trs.state == JobState.queued:
            jobid = trs.info
            jobndx = trs.jobndx

    if not jobid:
        _logger.warning("No queued job found to poll")
        return

    try:
        async with iri_session(job.info.backend) as (session, resource_id):
            # Query job status
            url = f"/api/v1/compute/status/{resource_id}/{jobid}"
            _logger.debug("Polling job status from IRI API: %s", url)

            async with session.get(url) as resp:
                if resp.status == 404:
                    _logger.warning("Job %s not found in IRI API", jobid)
                    return

                if resp.status != 200:
                    error_text = await resp.text()
                    _logger.error(
                        "Failed to poll job status (status %d): %s",
                        resp.status,
                        error_text,
                    )
                    return

                result = await resp.json()
                status = result.get("status")
                if not status:
                    _logger.error("IRI API response missing 'status' field: %s", result)
                    return

                # Map IRI state to psik state
                iri_state = status.get("state", "").upper()
                psik_state = IRI_STATE_MAP.get(iri_state)

                if not psik_state:
                    _logger.warning("Unknown IRI job state: %s", iri_state)
                    return

                # Check if this is a new state transition
                current_state = job.history[-1].state if job.history else JobState.new
                if psik_state != current_state:
                    _logger.info(
                        "Job %s state changed: %s -> %s",
                        jobid,
                        current_state,
                        psik_state,
                    )
                    # Use native_id from status if available, otherwise use jobid
                    info = status.get("native_id", jobid)
                    await job.reached(jobndx, psik_state, str(info))
                else:
                    _logger.debug("Job %s state unchanged: %s", jobid, psik_state)
            # need to test file download capability
            # to retrieve logs.
            #await download_file(session, resource_id, "psik/{jobid}/logs/console")

    except Exception as e:
        _logger.error("Error polling job status from IRI API: %s", e)


async def cancel(job: Job) -> None:
    """
    Cancel a job via the IRI API.
    """
    # Get all live job IDs
    jobinfos = await job.live_ids()
    
    if not jobinfos:
        _logger.warning("No live jobs to cancel")
        return
    
    async with iri_session(job.info.backend) as (session, resource_id):
        for jobid in jobinfos:
            url = f"/api/v1/compute/cancel/{resource_id}/{jobid}"
            _logger.info("Canceling job %s via IRI API: %s", jobid, url)
            
            try:
                async with session.delete(url) as resp:
                    if resp.status == 204:
                        _logger.info("Job %s canceled successfully", jobid)
                    elif resp.status == 404:
                        _logger.warning("Job %s not found (may already be finished)", jobid)
                    else:
                        error_text = await resp.text()
                        _logger.error(
                            "Failed to cancel job %s (status %d): %s",
                            jobid,
                            resp.status,
                            error_text,
                        )
            except Exception as e:
                _logger.error("Error canceling job %s: %s", jobid, e)
