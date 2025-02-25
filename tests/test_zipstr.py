from psik.zipstr import str_to_dir, dir_to_str

def test_extract(tmp_path):
    a = tmp_path/"a"
    a.mkdir()
    b = tmp_path/"b"
    b.mkdir()
    (a/"x").mkdir()
    (a/"txt1").write_text("txt1\ntest file\n")
    (a/"txt2").write_text("txt2\ntest file\n")
    (a/"x"/"test.bin").write_bytes(b"subdir\0test\0")

    s = dir_to_str(a)
    print(f"Encoded to string w. length {len(s)}")
    str_to_dir(s, b)
    for f in b.iterdir():
        if f.name.startswith("txt"):
            assert f.is_file()
            assert f.read_text() == f"{f.name}\ntest file\n"
        else:
            assert f.name == "x"
            assert f.is_dir()
            for g in f.iterdir():
                assert g.name == "test.bin"
                assert g.is_file()
                assert g.read_bytes() == b"subdir\0test\0"

#if __name__=="__main__":
#    from pathlib import Path
#    wd = Path("tmp")
#    wd.mkdir(exist_ok=True)
#    test_extract(wd)
