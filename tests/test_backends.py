import sys
import pytest

from psik.manager import JobManager
from psik.models import JobSpec
from psik.config import load_config
from psik.templates import list_backends

def test_backends():
    backends = list_backends()
    assert len(backends) >= 4

@pytest.mark.skipif(sys.platform == 'darwin', reason="OSX eschews batch/at")
@pytest.mark.asyncio
async def test_at(tmp_path):
    backend = 'at'
    base = tmp_path/backend
    base.mkdir()

    mgr = JobManager(tmp_path, backend)
    spec = JobSpec(name="hello",
               script = """#!/usr/bin/env rc
               echo Look out! >[1=2]
               sleep 60
               echo rawr >lion
           """)

    job = await mgr.create(spec)
    ok = await job.submit()
    assert ok
    assert len(job.history) == 2 # new, queued
    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (tmp_path/'log'/'stderr.1').read_text() == 'Look out!\n'
