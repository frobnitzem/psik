import sys
import pytest
from typing import Any

from aiohttp import web

from psik.manager import JobManager
from psik.models import JobSpec, JobState, BackendConfig, Callback, Transition
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
    jobndx, native_id = await job.submit()
    assert len(job.history) == 2 # new, queued
    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    assert isinstance(job.history[0], Transition)
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (job.base/'log'/'stderr.1').read_text() == 'Look out!\n'

@pytest.mark.asyncio
async def test_local(tmp_path):
    backend = BackendConfig(type = "local")
    config = Config(prefix = tmp_path, backends = {"local":backend})

    mgr = JobManager(config)
    spec = JobSpec(name="hello",
               script = """#!/usr/bin/env rc
               echo Look out! >[1=2]
               sleep 2
               echo rawr >lion
           """, backend="local")

    job = await mgr.create(spec)
    jobndx, pid = await job.submit()
    assert len(job.history) == 2 # new, queued
    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (job.base/'log'/'stderr.1').read_text() == 'Look out!\n'

value = web.AppKey("value", None) # type: ignore[var-annotated]

async def post_cb(request):
    if request.method != 'POST':
        raise KeyError(request.method)
    request.app[value] = await request.json()
    #body = await request.post()
    #print(f"test cb received: {body}")
    return web.Response(body=b'OK')

@pytest.fixture
def cb_server(event_loop, aiohttp_server):
    app = web.Application()
    app.router.add_post('/callback', post_cb)
    return event_loop.run_until_complete(aiohttp_server(app))

@pytest.mark.asyncio
async def test_local_cb(cb_server, aiohttp_server, tmp_path):
    server = cb_server
    #print(server.make_url('/callback'), server.scheme, server.host, server.port)
    # note also server.app

    backend = BackendConfig(type = "local")
    config = Config(prefix = tmp_path, backends = {"local":backend})

    mgr = JobManager(config)
    spec = JobSpec(name = "hello",
                   callback = str(server.make_url("/callback")),
                   script = """#!/usr/bin/env rc
                   echo Look out! >[1=2]
                   sleep 2
                   echo rawr >lion
           """, backend="local")

    job = await mgr.create(spec)
    jobndx, pid = await job.submit()
    assert len(job.history) == 2 # new, queued
    ans = server.app[value]
    print(f"test cb received: {ans}")
    # {'jobid': '12.345', 'jobndx': 1, 'state': 'queued', 'info': <pid>}
    cb = Callback.model_validate(ans)
    assert cb.jobid == job.stamp
    assert cb.jobndx == jobndx
    assert cb.state == JobState.queued
    assert cb.info == pid

    await job.cancel()
    assert len(job.history) > 2 # new, queued, canceled
    ans = server.app[value]
    print(f"test cb received: {ans}")
    # {'jobndx': 0, 'state': 'canceled', 'info': 0}
    cb = Callback.model_validate(ans)
    assert cb.jobid == job.stamp
    assert cb.jobndx >= 0
    assert cb.state == JobState.canceled
    
    print(job.history)
    if len(job.history) > 3: # new, queued, started, canceled
        assert (job.base/'log'/'stderr.1').read_text() == 'Look out!\n'
