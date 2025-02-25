from typing_extensions import Annotated
from typing import Optional, Dict, Any, Tuple
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, SecretStr, ConfigDict
from pydantic.types import StringConstraints

JobID = Annotated[str, StringConstraints(pattern=r'^[0-9]+(\.[0-9]+)?$')]

class JobState(str, Enum):
    new = "new"
    queued = "queued"
    active = "active"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"

    def is_final(self) -> bool:
        return self.value in ["completed", "failed", "canceled"]

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
    model_config = ConfigDict(extra="forbid")
    type              : str = "local"
    queue_name        : Optional[str] = None
    project_name      : Optional[str] = None
    reservation_id    : Optional[str] = None
    attributes        : Dict[str,str] = {} # backend config. options

class JobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name        : Optional[str] = Field(default=None, title="Job name")
    directory   : Optional[str] = Field(default=None, title="Job run directory")
    script      : str = Field(..., title="Shell / shebang script to execute")

    environment : Dict[str,str] = Field(default={},title="custom environment variables")
    inherit_environment : bool  = Field(default=True, title="If this flag is set to False, the job starts with an empty environment.")

    resources   : ResourceSpec  = Field(default=ResourceSpec(), title="Job resource requirements")
    backend     : str           = Field(default="default", title="Configured backend name")
    attributes  : Dict[str,str] = Field(default={}, title="Backend attribute values.")
    # deps       : List[str]     = Field(default=[], title="Dependencies required before starting this job.")
    callback    : Optional[str] = Field(default=None, title="URL to send event notifications.")
    cb_secret   : Optional[SecretStr] = Field(default=None, title="hmac256 secret to sign updates sent to 'callback'")
    client_secret : Optional[SecretStr] = Field(default=None, title="hmac256 secret to validate callback updates from clients")

#j = JobSpec(script="mpirun hostname")
#print(j.json())

class Transition(BaseModel):
    time:   float
    jobndx: int
    state:  JobState
    info:   int

    def fields(self) -> Tuple[float,int,str,int]:
        return self.time, self.jobndx, self.state.value, self.info

# Data models specific to status routes:
class Callback(BaseModel):
    jobid   : JobID = Field(..., title="Job ID")
    jobndx  : int   = Field(..., title="Sequential job index.")
    state   : JobState = Field(..., title="State reached by job.")
    info    : int = Field(default=0, title="Status code.")

def load_jobspec(fname):
    data = Path(fname).read_text(encoding='utf-8')
    if fname.endswith("yaml") or fname.endswith("yml"):
        import yaml # type: ignore[import-untyped]
        return JobSpec.model_validate( yaml.safe_load(data) )
    return JobSpec.model_validate_json(data)
