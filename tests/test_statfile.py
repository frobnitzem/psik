
import pytest
from anyio import Path as aPath

from psik.statfile import append_csv, read_csv

@pytest.mark.asyncio
async def test_read_write(tmp_path):
    f = aPath(tmp_path) / 'data.csv'
    await append_csv(f, 1010221.231, 'initial',   0)
    await append_csv(f, 1010222.131, 'queued',  320)
    await append_csv(f, 1010224.431, 'cancelled', 1)
    
    ans = await read_csv(f)
    assert len(ans) == 3
    for t in ans:
        assert len(t) == 3
        assert t[0][:3] == "101"
