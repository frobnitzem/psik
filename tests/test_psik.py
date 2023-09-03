from pathlib import Path

import pytest
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

    result = runner.invoke(app, ["run", "--config", cfg, "--no-submit", spec])
    print(result.stdout)
    assert result.exit_code == 0

    jobs = list(base.iterdir())
    assert len(jobs) == 1
    jobname = str(jobs[0])
    job = str(base / jobname)

    result = runner.invoke(app, ["run", "--config", cfg, spec])
    print(result.stdout)
    assert result.exit_code == 0
    jobs = list(base.iterdir())
    assert len(jobs) == 2

    result = runner.invoke(app, ["reached", job, "active"])
    assert result.exit_code != 0

    result = runner.invoke(app, ["reached", job, "0", "active"])
    print(job, "active")
    print(result.stdout)
    assert result.exit_code == 0

    result = runner.invoke(app, ["cancel", job])
    print(result.stdout)
    assert result.exit_code == 0

    result = runner.invoke(app, ["ls", "--config", cfg])
    assert result.exit_code == 0
    assert result.stdout.count('\n') >= 2

    result = runner.invoke(app, ["status", "--config", cfg, jobname])
    assert result.exit_code == 0
