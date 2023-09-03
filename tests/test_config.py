from pathlib import Path
import os

import pytest

from psik.config import load_config, Config
from psik.manager import JobManager
from psik.models import JobSpec, ResourceSpec, JobAttributes, JobState
import psik.templates as templates

cfg = """{
"prefix": "%s",
"backend": "local",
"default_attr": {
    "project_name": "my_proj",
    "custom_attributes": {
            "srun": {"--gpu-bind": "closest"},
            "jsrun": {"-b": "packed:rs"}
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
    assert config.backend == "local"
    assert isinstance(config.default_attr, JobAttributes)

@pytest.mark.asyncio
async def test_create(tmp_path):
    config = load_config( write_config(tmp_path) )
    base = Path(config.prefix) / config.backend
    assert base.is_dir()

    mgr = JobManager(config.prefix, config.backend)
    spec = JobSpec(
                name = "foo",
                script = "hostname",
                resources = ResourceSpec(),
                attributes = JobAttributes(),
           )
    job = await mgr.create(spec)
    # default choice
    assert job.spec.directory == str(job.base / 'work')
    assert job.base == base / job.stamp
    assert await (job.base / 'log').is_dir()
    assert await (job.base / 'work').is_dir()
    assert await (job.base / 'scripts').is_dir()

    assert os.access(Path(job.base) / 'scripts' / 'run', os.X_OK)
    for act in templates.actions:
        assert os.access(Path(job.base) / 'scripts' / act, os.X_OK)
    for state in JobState:
        if state == JobState.new: continue
        if state == JobState.queued: continue
        name = state.value
        assert os.access(Path(job.base) / 'scripts' / f'on_{name}', os.X_OK)
    async for f in (job.base / 'scripts').iterdir():
        print(f"======== {f} ========")
        print(await f.read_text())
        print()
