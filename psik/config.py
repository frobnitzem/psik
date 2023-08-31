from typing import Optional
import os
from pathlib import Path

from pydantic import BaseModel

from .models import JobAttributes

class Config(BaseModel):
    prefix       : str
    backend      : str
    default_attr : JobAttributes = JobAttributes()

default_attr = JobAttributes(
       project_name = "stf006",
       # custom attributes to bind processes to hardware correctly
       custom_attributes = {
             "srun": {"--gpu-bind": "closest"},
             "jsrun": {"-b": "packed:rs"},
           }
       )

def load_config(path : Optional[str]) -> Config:
    cfg_name = 'psik.json'
    if path is None:
        path = Path(os.environ["HOME"]) / '.config' / cfg_name
    else:
        path = Path(path)
    assert path.exists(), f"{cfg_name} is required to exist (tried {path})"
    config = Config.model_validate_json(path.read_text(encoding='utf-8'))
    (Path(config.prefix)/config.backend).mkdir(parents=True, exist_ok=True)
    return config
