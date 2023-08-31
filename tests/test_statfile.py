from psik.statfile import append_csv, read_csv

def test_read_write(tmp_path):
    f = tmp_path / 'data.csv'
    append_csv(f, 1010221.231, 'initial',   0)
    append_csv(f, 1010222.131, 'queued',  320)
    append_csv(f, 1010224.431, 'cancelled', 1)
    
    ans = read_csv(f)
    assert len(ans) == 3
    for t in ans:
        assert len(t) == 3
        assert t[0][:3] == "101"

