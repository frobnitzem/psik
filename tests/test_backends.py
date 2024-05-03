import sys
import pytest

from psik.manager import JobManager
from psik.models import JobSpec, BackendConfig
from psik.config import Config
from psik.templates import list_backends

def test_backends():
    backends = list_backends()
    assert len(backends) >= 4

#@pytest.mark.skipif(sys.platform == 'darwin', reason="OSX eschews batch/at")
@pytest.mark.skip
@pytest.mark.asyncio
async def test_at(tmp_path):
    backend = BackendConfig(type = "at")
    config = Config(prefix = tmp_path, backend = backend)

    mgr = JobManager(config)
    spec = JobSpec(name="hello",
               script = """#!/usr/bin/env rc
               echo Look out! >[1=2]
               sleep 2
               echo rawr >lion
           """)

    job = await mgr.create(spec)
    await job.submit()
    assert len(job.history) == 2 # new, queued
    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (job.base/'log'/'stderr.1').read_text() == 'Look out!\n'

@pytest.mark.asyncio
async def test_local(tmp_path):
    backend = BackendConfig(type = "local")
    config = Config(prefix = tmp_path, backend = backend)

    mgr = JobManager(config)
    spec = JobSpec(name="hello",
               script = """#!/usr/bin/env rc
               echo Look out! >[1=2]
               sleep 2
               echo rawr >lion
           """)

    job = await mgr.create(spec)
    await job.submit()
    assert len(job.history) == 2 # new, queued
    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (job.base/'log'/'stderr.1').read_text() == 'Look out!\n'
