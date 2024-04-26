from typing import Union
from functools import cache
import os
import sys
from pathlib import Path

from pydantic import BaseModel

from .models import JobAttributes

@cache
def psik_path() -> str:
    ans = os.path.join(os.path.dirname(sys.executable), "psik")
    if os.access(ans, os.X_OK):
        return ans
    return "psik"

class Config(BaseModel):
    prefix       : str
    backend      : str
    default_attr : JobAttributes = JobAttributes()

def load_config(path1 : Union[str, Path, None]) -> Config:
    cfg_name = 'psik.json'
    if path1 is not None:
        path = Path(path1)
    else:
        if "PSIK_CONFIG" in os.environ:
            path = Path(os.environ["PSIK_CONFIG"])
        else:
            path = Path(os.environ["HOME"]) / '.config' / cfg_name
    assert path.exists(), f"{cfg_name} is required to exist (tried {path})"
    config = Config.model_validate_json(path.read_text(encoding='utf-8'))
    # Ensure the backend directory exists.
    (Path(config.prefix)/config.backend).mkdir(parents=True, exist_ok=True)
    return config
