import os

import pytest

from redtogreen.config import DEFAULT_PROTECTED
from redtogreen.workspace import Workspace, WorkspaceError


@pytest.fixture
def ws(mini_repo, tmp_path):
    return Workspace.from_directory(mini_repo, tmp_path / "ws", DEFAULT_PROTECTED)


@pytest.mark.parametrize("bad", ["../outside.txt", "/etc/passwd", "tests/../../x", ".git/config", "", "a\x00b"])
def test_rejects_paths_outside_the_repo(ws, bad):
    with pytest.raises(WorkspaceError):
        ws.resolve(bad)


def test_rejects_symlink_escape(ws, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    os.symlink(secret, ws.root / "link.txt")
    with pytest.raises(WorkspaceError):
        ws.read_file("link.txt")


def test_read_file_numbers_lines_and_paginates(ws):
    out = ws.read_file("calc.py", start_line=2, end_line=2)
    assert "    2      return a - b" in out
    assert "lines 2-2 of 6" in out


def test_list_and_search(ws):
    assert ws.list_files() == ["calc.py", "tests/test_calc.py"]
    hits = ws.search(r"def \w+", file_glob="*.py")
    assert "calc.py:1: def add(a, b):" in hits


def test_replace_exactly_once(ws):
    with pytest.raises(WorkspaceError, match="not found"):
        ws.replace_in_file("calc.py", "a * b", "a + b")
    with pytest.raises(WorkspaceError, match="appears 2 times"):
        ws.replace_in_file("calc.py", "    return", "    return")
    ws.replace_in_file("calc.py", "return a - b", "return a + b")
    assert "return a + b" in ws.file_text("calc.py")


def test_cannot_edit_tests(ws):
    with pytest.raises(WorkspaceError, match="protected"):
        ws.replace_in_file("tests/test_calc.py", "== 5", "== -1")


def test_diff_stats_and_reset(ws):
    ws.replace_in_file("calc.py", "return a - b", "return a + b")
    stats = ws.patch_stats()
    assert stats.files == ["calc.py"] and stats.added == 1 and stats.removed == 1
    assert "+    return a + b" in ws.diff()
    ws.reset()
    assert ws.diff() == "" and ws.changed_files() == []
