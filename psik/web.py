from typing import Optional, Any
import hmac
import hashlib
import re
import logging
_logger = logging.getLogger(__name__)

import aiohttp
from aiohttp.web import HTTPForbidden

def verify_signature(payload_body : str, secret_token : str,
                     signature_header : Optional[str]) -> None:
    """Verify that the payload was sent from GitHub by validating SHA256.

    Raise and return 403 if not authorized.

    Args:
        payload_body: original request body to verify (request.body())
        secret_token: GitHub app webhook token (WEBHOOK_SECRET)
        signature_header: header received from GitHub (x-hub-signature-256)
    """
    if not signature_header:
        raise HTTPForbidden(reason="x-hub-signature-256 header is missing!")
    expected_signature = sign_message(payload_body, secret_token)
    if not hmac.compare_digest(expected_signature, signature_header):
        raise HTTPForbidden(reason="Request signatures didn't match!")

def sign_message(payload_body : str, secret_token : str) -> str:
    hash_object = hmac.new(secret_token.encode("utf-8"),
                           msg=payload_body.encode("utf-8"),
                           digestmod=hashlib.sha256)
    return "sha256=" + hash_object.hexdigest()

async def get_json(url : str,
                   token : Optional[str] = None) -> Optional[Any]:
    headers = {}
    headers['Accept'] = 'application/json'
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None
            if token:
                hdr = response.headers["x-hub-signature-256"]
                val = await response.text()
                verify_signature(val, token, hdr)
            #print("Content-type:", response.headers['content-type'])
            return await response.json()
            #return await response.text()

async def post_json(url : str,
                    info : str,
                    token : Optional[str] = None) -> Optional[Any]:
    headers = {"content-type": "application/json"}
    headers["Accept"] = "application/json"
    if token:
        headers["x-hub-signature-256"] = sign_message(info, token)
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=info, headers=headers) \
                    as response:
            if response.status != 200:
                return None
            #print("Content-type:", response.headers['content-type'])
            if response.headers['content-type'] == 'application/json':
                return await response.json()
            return await response.text()

if __name__=="__main__":
    import asyncio
    async def f():
        ans = await post_json("http://127.0.0.1:8000/compute/jobs/default",
                '{"name": "hello", "script": "echo hello; pwd"}',
                "secret token")
        print(ans)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(f())

