from redtogreen.config import DEFAULT_PROTECTED
from redtogreen.policy import PatchStats, check_patch, is_protected


def test_protected_paths():
    for path in ["tests/test_x.py", "tests/unit/deep/helpers.py", "pkg/tests/test_y.py", "test_top.py",
                 "pkg/test_mod.py", "pkg/mod_test.py", "conftest.py", "pkg/conftest.py",
                 ".github/workflows/ci.yml", "./tests/a.py", "pyproject.toml", "requirements-dev.txt"]:
        assert is_protected(path, DEFAULT_PROTECTED), path


def test_source_files_are_editable():
    for path in ["calc.py", "shopkit/pricing.py", "src/app/testing_utils.py", "contest.py", "github/api.py"]:
        assert not is_protected(path, DEFAULT_PROTECTED), path


def test_check_patch_limits():
    ok = PatchStats(files=["a.py"], added=2, removed=1)
    assert check_patch(ok, DEFAULT_PROTECTED, max_files=3, max_lines=80) == []

    too_big = PatchStats(files=["a.py", "b.py", "c.py", "d.py"], added=100, removed=0)
    violations = check_patch(too_big, DEFAULT_PROTECTED, max_files=3, max_lines=80)
    assert len(violations) == 2

    touches_tests = PatchStats(files=["tests/test_a.py"], added=1, removed=1)
    assert "protected" in check_patch(touches_tests, DEFAULT_PROTECTED, 3, 80)[0]
