from typing import Optional, Any
import re
import logging
_logger = logging.getLogger(__name__)

import aiohttp

async def get_json(url) -> Optional[Any]:
    headers = {}
    headers['Accept'] = 'application/json'
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                return None
            #print("Content-type:", response.headers['content-type'])
            return await response.json()
            #return await response.text()

async def post_json(url, info) -> Optional[Any]:
    headers = {}
    headers['Accept'] = 'application/json'
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=info, headers=headers) \
                    as response:
            if response.status != 200:
                return None
            #print("Content-type:", response.headers['content-type'])
            return await response.json()

if __name__=="__main__":
    import asyncio
    async def f():
        ans = await post_json("http://127.0.0.1:8000/compute/jobs/default",
                {"name": "hello", "script": "echo hello; pwd"})
        print(ans)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(f())
