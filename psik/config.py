from typing import Union, Dict
from functools import cache
import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict

from .models import BackendConfig

class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefix       : Path = Field(title="prefix for psik output")
    backends     : Dict[str,BackendConfig] = Field(
                                 default = {"default":BackendConfig()},
                                 title = "backend configurations"
                               )

def load_config(path1 : Union[str, Path, None]) -> Config:
    cfg_name = "psik.json"
    if path1 is not None:
        path = Path(path1)
    else:
        if "PSIK_CONFIG" in os.environ:
            path = Path(os.environ["PSIK_CONFIG"])
        else:
            path = Path(os.environ.get("VIRTUAL_ENV", "/")) / "etc" / cfg_name
    assert path.exists(), f"{cfg_name} is required to exist (tried {path})"
    config = Config.model_validate_json(path.read_text(encoding='utf-8'))

    # Ensure the backend directory exists.
    config.prefix.mkdir(parents=True, exist_ok=True)
    # Ensure the psik/rc paths exist - note these may not exist on
    # the submitting host.
    return config
