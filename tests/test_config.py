from pathlib import Path

from psik.config import load_config, Config
from psik.manager import JobManager
from psik.models import JobSpec, ResourceSpec, JobAttributes

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

def test_create(tmp_path):
    config = load_config( write_config(tmp_path) )
    base = Path(config.prefix) / config.backend
    assert base.is_dir()

    mgr = JobManager(base)
    spec = JobSpec(
                name = "foo",
                script = "hostname",
                resources = ResourceSpec(),
                attributes = JobAttributes(),
           )
    job = mgr.create(spec)
    # default choice
    assert job.spec.directory == str(job.base / 'work')
    assert job.base == base / job.stamp
    assert (job.base / 'scripts').is_dir()
    for f in (job.base / 'scripts').glob('*'):
        print(f)
        print(f.read_text())
        print()
