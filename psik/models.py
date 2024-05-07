from typing import Optional, Dict, Any
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr

class JobState(str, Enum):
    new = "new"
    queued = "queued"
    active = "active"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"

class ResourceSpec(BaseModel):
    duration              : int = Field(default=10, title="Max walltime of the job in minutes")  
    node_count            : Optional[int] = Field(default=None, title="Number of compute nodes allocated to job.")
    process_count         : Optional[int] = Field(default=None, title="Instruct the backend to start this many process instances. Mutually exclusive with node+processes_per_node. Default if neither is 1 process.")
    processes_per_node    : Optional[int] = None
    cpu_cores_per_process : int = Field(default=1, title="CPU cores for each process instance.") 
    gpu_cores_per_process : int = 0
    exclusive_node_use    : bool = True

# Was JobAttributes.  However, these are actually
# backend configuration options.
#
# Hence `custom_attributes` is renamed to
# `attributes`, since it applies to this specific backend.
#
# Nevertheless, these can be specified/overriden as part of a JobSpec,
# so they should not include API-unsafe values (e.g. psik path,
# server hostname, etc.)
class BackendConfig(BaseModel):
    type              : str = "local"
    queue_name        : Optional[str] = None
    project_name      : Optional[str] = None
    reservation_id    : Optional[str] = None
    attributes        : Dict[str,str] = {} # backend config. options

class JobSpec(BaseModel):
    name        : Optional[str] = Field(default=None, title="Job name")
    directory   : Optional[str] = Field(default=None, title="Job run directory")
    script      : str = Field(..., title="Shell / shebang script to execute")

    environment : Dict[str,str] = Field(default={},title="custom environment variables")
    inherit_environment : bool  = Field(default=True, title="If this flag is set to False, the job starts with an empty environment.")

    resources   : ResourceSpec  = Field(default=ResourceSpec(), title="Job resource requirements")
    backend     : BackendConfig = Field(default=BackendConfig(), title="Backend configuration values.")
    # deps       : List[str]     = Field(default=[], title="Dependencies required before starting this job.")
    callback    : Optional[str] = Field(default=None, title="URL to send event notifications.")
    cb_secret   : Optional[SecretStr] = Field(default=None, title="hmac256 secret to sign updates sent to 'callback'")
    client_secret : Optional[SecretStr] = Field(default=None, title="hmac256 secret to validate callback updates from clients")

#j = JobSpec(script="mpirun hostname")
#print(j.json())

# Data models specific to status routes:
class Callback(BaseModel):
    jobndx  : int = Field(..., title="Sequential job index.")
    state   : JobState = Field(..., title="State reached by job.")
    info    : int = Field(default=0, title="Status code.")

def load_jobspec(fname):
    return JobSpec.model_validate_json(
                Path(fname).read_text(encoding='utf-8'))
