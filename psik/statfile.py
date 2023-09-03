from typing import (
    Union,
    TypeVar,
    Callable,
    Any,
    Awaitable,
    Optional,
    List,
    cast
)
from functools import wraps, partial
from pathlib import Path
from fcntl import flock, LOCK_UN, LOCK_SH, LOCK_EX, LOCK_NB
import asyncio

from anyio import Path as aPath
from anyio import open_file, AsyncFile

# from https://github.com/kumaraditya303/aioshutil/blob/master/aioshutil/__init__.py
T = TypeVar("T", bound=Callable[..., Any])
def sync_to_async(func: T) -> Awaitable[T]:
    @wraps(func)
    async def run_in_executor(*args, **kwargs):
        loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(None, pfunc)

    return cast(Awaitable[T], run_in_executor)

aflock = sync_to_async(flock)

class FLock:
    """ flock context manager that works
        in both regular (with Flock(): ...)
        and async mode (async with Flock(): ...)
    """
    def __init__(self, fd, flags):
        self.fd, self.op = fd, flags
    async def __aenter__(self):
        await aflock(self.fd, self.op)
        return self
    async def __aexit__(self, exc_type, exc_value, traceback):
        await aflock(self.fd, LOCK_UN)
        return False

    def __enter__(self):
        flock(self.fd, self.op)
        return self
    def __exit__(self, exc_type, exc_value, traceback):
        flock(self.fd, LOCK_UN)
        return False

class ReadLock(FLock):
    """ReadLock context manager based on
       https://github.com/misli/python-flock

       Example:

       with open('/tmp/file.lock', 'r') as f:
         with ReadLock(f):
           pass

         try:
           with ReadLock(f, blocking=False):
             pass
         except BlockingIOError:
           pass

       async Example:

       async with anyio.open_file('/tmp/file.lock', 'r') as f:
         async with ReadLock(f):
           pass

         try:
           async with ReadLock(f, blocking=False):
             pass
         except BlockingIOError:
           pass
    """

    def __init__(self, fd, blocking=True):
        flags = LOCK_SH
        if blocking:
            flags |= LOCK_NB
        super().__init__(fd, flags)

class WriteLock(FLock):
    """WriteLock context manager based on
       https://github.com/misli/python-flock

       See ReadLock for usage examples.
    """

    def __init__(self, fd, blocking=True):
        flags = LOCK_EX
        if blocking:
            flags |= LOCK_NB
        super().__init__(fd, flags)

async def append_csv(f : Union[str,Path,aPath,AsyncFile], *vals) -> None:
    if isinstance(f, AsyncFile):
        async with WriteLock(f):
            await f.write(','.join(map(str, vals)) + '\n')
    else:
        async with await open_file(f, 'a', encoding='utf-8') as f2:
            async with WriteLock(f2):
                await f2.write(','.join(map(str, vals)) + '\n')

async def read_csv(f : Union[str,Path,aPath,AsyncFile]) -> List[str]:
    if isinstance(f, AsyncFile):
        async with ReadLock(f):
            lines = await f.readlines()
    else:
        async with await open_file(f, 'r', encoding='utf-8') as f2:
            async with ReadLock(f2):
                lines = await f2.readlines()
    return [ l.strip().split(',') for l in lines ]

async def create_file(name : aPath, content : str,
                      perm : Optional[int] = None) -> None:
    async with await name.open('w', encoding='utf-8') as f:
        if perm is not None:
            await name.chmod(perm)
        await f.write(content)
        # Unless completely empty, ensure a final newline.
        if not (len(content) == 0 or content.endswith('\n')):
            await f.write('\n')
