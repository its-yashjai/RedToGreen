import shutil
import subprocess
from pathlib import Path

import pytest

from redtogreen.config import Settings, get_settings
from redtogreen.db import session as db_session
from redtogreen.db.models import Base

MINI_SOURCE = '''def add(a, b):
    return a - b


def double(x):
    return x * 2
'''
MINI_TEST = '''from calc import add, double


def test_add():
    assert add(2, 3) == 5


def test_double():
    assert double(4) == 8
'''


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings for tests: local sandbox, short timeouts, a temp work dir, no .env file."""
    return Settings(_env_file=None, sandbox_backend="local", workdir=tmp_path / "work", sandbox_timeout_s=60,
                    max_attempts=3, max_steps_per_attempt=8, llm_provider="fake")


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A two-function project whose `add` is broken (a - b instead of a + b)."""
    repo = tmp_path / "mini"
    (repo / "tests").mkdir(parents=True)
    (repo / "calc.py").write_text(MINI_SOURCE)
    (repo / "tests" / "test_calc.py").write_text(MINI_TEST)
    return repo


@pytest.fixture
def db(tmp_path: Path, monkeypatch):
    """A fresh SQLite database wired into session_scope()."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session._factory.cache_clear()
    Base.metadata.create_all(db_session.get_engine())
    yield
    db_session.get_engine().dispose()
    get_settings.cache_clear()
    db_session.get_engine.cache_clear()
    db_session._factory.cache_clear()


def docker_ready(image: str = "redtogreen-sandbox:latest") -> bool:
    if not shutil.which("docker"):
        return False
    result = subprocess.run(["docker", "image", "inspect", image], capture_output=True, check=False)
    return result.returncode == 0
