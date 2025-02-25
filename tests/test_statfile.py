from pathlib import Path

import pytest
from anyio import Path as aPath
from anyio import open_file

from psik.statfile import append_csv, read_csv, ReadLock, WriteLock

@pytest.mark.asyncio
async def test_read_write_fd(tmp_path):
    f = aPath(tmp_path) / 'data.csv'
    async with await open_file(f, 'a', encoding='utf-8') as fd:
        await append_csv(fd, 1010221.231, 'initial',   0)
        await append_csv(fd, 1010222.131, 'queued',  320)
        await append_csv(fd, 1010224.431, 'cancelled', 1)
    
    async with await open_file(f, 'r', encoding='utf-8') as fd:
        ans = await read_csv(fd)
    assert len(ans) == 3
    for t in ans:
        assert len(t) == 3
        assert t[0][:3] == "101"

@pytest.mark.asyncio
async def test_read_write_path(tmp_path):
    f = aPath(tmp_path) / 'data.csv'
    await append_csv(f, 1010221.231, 'initial',   0)
    await append_csv(f, 1010222.131, 'queued',  320)
    await append_csv(f, 1010224.431, 'cancelled', 1)
    
    ans = await read_csv(f)
    assert len(ans) == 3
    for t in ans:
        assert len(t) == 3
        assert t[0][:3] == "101"

def test_non_async(tmp_path):
    f = Path(tmp_path) / 'data.csv'
    def add(f, *vals):
        with open(f, 'a', encoding='utf-8') as fd:
            with WriteLock(fd):
                fd.write(','.join(map(str, vals)) + '\n')
    add(f, 1010221.231, 'initial',   0)
    add(f, 1010222.131, 'queued',  320)
    add(f, 1010224.431, 'cancelled', 1)
    
    with open(f, 'r', encoding='utf-8') as fd:
        with ReadLock(fd):
            lines = [ l.strip().split(',') for l in fd.readlines() ]
    assert len(lines) == 3
    for t in lines:
        assert len(t) == 3
        assert t[0][:3] == "101"
