import asyncio

import pytest
import pytest_asyncio

from aiohttp import web
from aiohttp.web import HTTPClientError, HTTPForbidden

from psik.web import (
    sign_message,
    verify_signature,
    post_json,
    #get_json,
)

### test fixture for accepting a callback ###
cb_value = web.AppKey("value", None) # type: ignore[var-annotated]

async def post_cb(request):
    if request.method != 'POST':
        raise KeyError(request.method)
    request.app[cb_value] = await request.json()
    #body = await request.post()
    #print(f"test cb received: {body}")
    return web.Response(text='OK', status=200)
    #return web.Response(body=b'"OK"', content_type="application/json", status=200)

@pytest_asyncio.fixture
async def cb_client(aiohttp_client):
    app = web.Application()
    app.router.add_post('/callback', post_cb)
    return await aiohttp_client(app)

def test_sign():
    ans = sign_message("Hello, World!", "It's a Secret to Everybody")
    assert ans == "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"

def test_verify():
    ans = sign_message("X", "Y")
    verify_signature("X", "Y", ans)
    with pytest.raises(HTTPClientError):
        verify_signature("X", "X", ans)
    with pytest.raises(HTTPClientError):
        verify_signature("Y", "Y", ans)
    with pytest.raises(HTTPForbidden):
        verify_signature("X", "Y", None)

@pytest.mark.asyncio
async def test_local_cb(cb_client):
    cb_server = cb_client.server
    ans = await post_json(str(cb_server.make_url("/callback")),
                '{"name": "hello", "script": "echo hello; pwd"}',

                "secret token")
    assert isinstance(cb_server.app[cb_value], dict)
    assert cb_server.app[cb_value]["name"] == "hello"
