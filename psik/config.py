from typing import Union
from functools import cache
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

from .models import BackendConfig

_self_path = Path(os.path.dirname(sys.executable)) / "psik"
_rc_path   = "/usr/bin/env rc"

class Config(BaseModel):
    prefix       : Path                               # prefix for psik output
    backend      : BackendConfig = BackendConfig()    # backend configuration
    psik_path    : Path = Field(default = _self_path) # path to psik executable
    rc_path      : str = Field(default = _rc_path)    # path to rc executable

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
    config.prefix.mkdir(parents=True, exist_ok=True)
    # Ensure the psik/rc paths exist - note these may not exist on
    # the submitting host.
    #assert os.access(config.psik_path, os.X_OK), 
    #assert os.access(config.rc_path, os.X_OK), 
    return config
