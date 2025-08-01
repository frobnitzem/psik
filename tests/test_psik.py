from pathlib import Path
import os
import re

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
    base = config.prefix

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

    result = runner.invoke(app, ["run", "-v", "--config", cfg, spec])
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

    result = runner.invoke(app, ["cancel", "--config", cfg, "-vv", job])
    print(result.stdout)
    assert result.exit_code == 0

    os.environ['PSIK_CONFIG'] = cfg
    result = runner.invoke(app, ["ls"])
    assert result.exit_code == 0
    assert result.stdout.count('\n') >= 2

    result = runner.invoke(app, ["status", "--config", cfg, jobname])
    assert result.exit_code == 0

    result = runner.invoke(app, ["rm", "--config", cfg, 'test'])
    assert result.exit_code == 1

    result = runner.invoke(app, ["rm", "--config", cfg, str(jobs[0])])
    assert result.exit_code == 0

    (base/jobs[1]).chmod(0o500)
    result = runner.invoke(app, ["rm", "--config", cfg, str(jobs[1])])
    assert result.exit_code == 1

    (base/jobs[1]).chmod(0o700)
    result = runner.invoke(app, ["rm", "--config", cfg, str(jobs[1])])
    assert result.exit_code == 0

def test_start(tmp_path):
    cfg = write_config(tmp_path)
    config = load_config( cfg )
    base = config.prefix

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

    m = re.match(r"Created ([0-9.]*)", result.stdout)
    assert m is not None, "Invalid output from psik run"
    stamp = m[1]

    jobs = list(base.iterdir())
    assert len(jobs) == 1
    assert jobs[0].name == stamp

    result = runner.invoke(app, ["start", "-v", "--config", cfg, "123"])
    assert result.exit_code != 0

    result = runner.invoke(app, ["start", "-v", "--config", cfg, stamp])
    assert result.exit_code == 0
    result = runner.invoke(app, ["status", "--config", cfg, stamp])
    assert result.exit_code == 0
    print(result.stdout)
    #assert result.stdout.count('\n') >= 2
    assert "base:" in result.stdout
    assert "work:" in result.stdout
