from pathlib import Path
import os

import pytest

from psik.config import load_config, Config
from psik.manager import JobManager
from psik.models import JobSpec, ResourceSpec, BackendConfig, JobState
import psik.templates as templates

cfg = """{
  "prefix": "%s",
  "backends": {
    "default": {
      "type": "local",
      "project_name": "my_proj",
      "attributes": {
          "--gpu-bind": "closest",
          "-b": "packed:rs"
      }
    }
  }
}
"""

def write_config(tmp_path):
    prefix = Path(tmp_path/'prefix')
    config = tmp_path / 'psik.json'
    config.write_text(cfg % prefix, encoding='utf-8')
    return config

def test_config():
    config = Config.model_validate_json(cfg % "/tmp")
    assert str(config.prefix) == "/tmp"
    assert len(config.backends) == 1
    assert isinstance(config.backends["default"], BackendConfig)
    assert config.backends["default"].type == "local"

@pytest.mark.asyncio
async def test_create(tmp_path):
    config = load_config( write_config(tmp_path) )
    base = Path(config.prefix)
    assert base.is_dir()

    mgr = JobManager(config)
    spec = JobSpec(
                name = "foo",
                script = "hostname",
                resources = ResourceSpec(),
           )
    job = await mgr.create(spec)
    # default choice
    assert job.spec.directory == str(job.base / 'work')
    assert job.base == base / job.stamp
    assert await (job.base / 'log').is_dir()
    assert await (job.base / 'work').is_dir()
