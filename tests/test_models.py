from pathlib import Path
import os

import pytest
from pydantic import ValidationError

from psik.models import (
    BackendConfig,
    Callback,
    JobID,
    JobSpec,
    JobState,
    ResourceSpec,
    Transition,
)

def test_jobid():
    x = Callback(jobid="123", jobndx=0, state=JobState.new, info=1)
    assert x.jobid == "123"
    assert x.jobndx == 0
    assert x.state == JobState.new
    assert x.info == 1

    for fail in ["123.11178x", "123.11178.", "12.", ".33", "x12", "12e4"]:
        with pytest.raises(ValidationError):
            Callback(jobid=fail, jobndx=x.jobndx, state=x.state, info=x.info)
    for ok in ["0123.111", "0.123", "12", "42.123", "11111.1"]:
        Callback(jobid=ok, jobndx=x.jobndx, state=x.state, info=x.info)

    assert (JobState.canceled).is_final()
    assert not (JobState.active).is_final()
    ResourceSpec()
    BackendConfig(type="nonlocal")
    JobSpec(script="pwd")
    JobSpec(name="test", script="pwd")
    y = Transition(time=12.125, jobndx=-1, state=JobState.new, info=0)
    assert y.fields() == (12.125, -1, "new", 0)
    Callback(jobid="333.999", jobndx=1, state=JobState.canceled, info=0)
