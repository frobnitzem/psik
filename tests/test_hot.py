from pathlib import Path
import os, sys
import re

import pytest
from typer.testing import CliRunner

from psik import __version__
from psik.psik import app
from psik.config import load_config
from psik.zipstr import dir_to_str

from .test_config import write_config

def test_version():
    assert len(__version__.split('.')) == 3

runner = CliRunner()

@pytest.mark.skipif(sys.platform == 'darwin', reason="Fork+exit confuses OSX")
def test_hot_start(tmp_path):
    print(sys.platform)
    cfg = write_config(tmp_path)

    result = runner.invoke(app, ["hot-start", "--config", cfg])
    assert result.exit_code == 2
    #print(result.stdout)

    spec = r"""
    { "name": "foo",
      "script": "#!/bin/sh\npwd\nhostname\n"
    }
    """
    result = runner.invoke(app, ["hot-start", "--config", cfg, "123.456", "1", spec])
    print(result.stdout)
    assert result.exit_code == 0

    base = tmp_path/'prefix'/'123.456'
    assert base.is_dir()
    out = (base/'log'/'stdout.1').read_text()
    assert str(base/"work") in out
    err = (base/'log'/'stderr.1').read_text()
    assert err.strip() == ""
    stat = (base/'status.csv').read_text().split()
    assert len(stat) == 3
    assert 'completed' in stat[-1]

@pytest.mark.skipif(sys.platform == 'darwin', reason="Fork+exit confuses OSX")
def test_zhot_start(tmp_path):
    cfg = write_config(tmp_path)
    setup_dir = tmp_path/"setup"
    setup_dir.mkdir()
    (setup_dir/"data.txt").write_text("T = 298\n")
    zstr = dir_to_str(setup_dir)

    spec = r"""
    { "name": "foo",
      "script": "#!/bin/sh\ncat data.txt\n"
    }
    """
    result = runner.invoke(app, ["hot-start", "--config", cfg, "7001271.8271", "1", spec, zstr])
    print(result.stdout)
    assert result.exit_code == 0

    base = tmp_path/'prefix'/'7001271.8271'
    assert base.is_dir()
    out = (base/'log'/'stdout.1').read_text()
    assert "T = 298" in out
    err = (base/'log'/'stderr.1').read_text()
    assert err.strip() == ""
    stat = (base/'status.csv').read_text().split()
    assert len(stat) == 3
    assert 'completed' in stat[-1]
