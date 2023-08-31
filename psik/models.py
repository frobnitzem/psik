from typing import Optional, Dict, Any
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

class JobState(str, Enum):
    new = "new"
    queued = "queued"
    active = "active"
    completed = "completed"
    failed = "failed"
    canceled = "canceled"

class ResourceSpec(BaseModel):
    duration              : int = Field(10, title="Max walltime of the job in minutes")  
    node_count            : Optional[int] = Field(None, title="Number of compute nodes allocated to job.")
    process_count         : Optional[int] = Field(None, title="Instruct the backend to start this many process instances. Mutually exclusive with node+processes_per_node. Default if neither is 1 process.")
    processes_per_node    : Optional[int] = None
    cpu_cores_per_process : int = Field(1, title="CPU cores for each process instance.") 
    gpu_cores_per_process : int = 0
    exclusive_node_use    : bool = True

class JobAttributes(BaseModel):
    queue_name        : Optional[str] = None
    project_name      : Optional[str] = None
    reservation_id    : Optional[str] = None
    custom_attributes : Dict[str, Dict[str,str]] = {}

class JobSpec(BaseModel):
    name        : Optional[str] = Field(None, title="Job name")
    directory   : Optional[str] = Field(None, title="Job run directory")
    script      : str = Field(..., title="Shell / shebang script to execute")

    environment : Dict[str,str] = Field({},title="custom environment variables")
    inherit_environment : bool = Field(True, title="If this flag is set to False, the job starts with an empty environment.")

    resources : ResourceSpec = Field(ResourceSpec(), title="Job resource requirements")
    attributes : JobAttributes = Field(JobAttributes(), title="Time and job labels")

#j = JobSpec(script="mpirun hostname")
#print(j.json())

def load_jobspec(fname):
    return JobSpec.model_validate_json(
                Path(fname).read_text(encoding='utf-8'))
