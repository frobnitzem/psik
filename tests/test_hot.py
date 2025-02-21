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

def test_hot_start(tmp_path):
    cfg = write_config(tmp_path)

    result = runner.invoke(app, ["hot-start", "--config", cfg])
    assert result.exit_code == 2
    #print(result.stdout)

    spec = r"""
    { "name": "foo",
      "script": "#!/usr/bin/env rc\npwd\nhostname\n"
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
    assert len(stat) == 4
    assert 'completed' in stat[-1]
    
