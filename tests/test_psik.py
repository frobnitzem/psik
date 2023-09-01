from pathlib import Path

from typer.testing import CliRunner

from psik import __version__
from psik.psik import app
from psik.config import load_config

from .test_config import write_config

def test_version():
    assert len(__version__.split('.')) == 3

runner = CliRunner()

def test_ls(tmp_path):
    cfg = write_config(tmp_path)

    result = runner.invoke(app, ["ls", "--config", cfg])
    assert result.exit_code == 0

    print(result.stdout)

def test_app(tmp_path):
    cfg = write_config(tmp_path)
    config = load_config( cfg )
    base = Path(config.prefix) / config.backend

    spec = Path(tmp_path/'jobspec.json')
    spec.write_text(r"""
    { "name": "foo",
      "script": "#!/usr/bin/env rc\npwd >pwd\nhostname >host\n"
    }
    """)
    cfg = str(cfg)
    spec = str(spec)

    result = runner.invoke(app, ["run", "--config", cfg, "--test", spec])
    print(result.stdout)
    assert result.exit_code == 0

    jobs = list(base.glob("*"))
    assert len(jobs) == 1
    job1 = jobs[0]
    job = str(job1)

    result = runner.invoke(app, ["run", "--config", cfg, spec])
    print(result.stdout)
    assert result.exit_code == 0
    jobs = list(base.glob("*"))
    assert len(jobs) == 2

    result = runner.invoke(app, ["reached", job, "active"])
    assert result.exit_code != 0

    result = runner.invoke(app, ["reached", job, "0", "active"])
    print(result.stdout)
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", "--config", cfg])
    assert result.exit_code == 0
    assert result.stdout.count('\n') >= 2

    result = runner.invoke(app, ["status", "--config", cfg, job1.name])
    assert result.exit_code == 0
