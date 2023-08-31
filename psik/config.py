from typing import Union
import os
from pathlib import Path

from pydantic import BaseModel

from .models import JobAttributes

class Config(BaseModel):
    prefix       : str
    backend      : str
    default_attr : JobAttributes = JobAttributes()

def load_config(path1 : Union[str, Path, None]) -> Config:
    cfg_name = 'psik.json'
    if path1 is None:
        path = Path(os.environ["HOME"]) / '.config' / cfg_name
    else:
        path = Path(path1)
    assert path.exists(), f"{cfg_name} is required to exist (tried {path})"
    config = Config.model_validate_json(path.read_text(encoding='utf-8'))
    # Ensure the backend directory exists.
    (Path(config.prefix)/config.backend).mkdir(parents=True, exist_ok=True)
    return config
