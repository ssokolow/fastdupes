#execute with pytest

from fastdupes import find_dupes

def test_common_prefix(tmpdir):
    files = tmpdir.mkdir("files")
    file1 = files.join("file1")
    file2 = files.join("file2")
    file1.write("0"*1000000 + "1")
    file2.write("0"*1000000 + "2")
    groups = find_dupes([str(files)])
    assert len(groups) == 0
