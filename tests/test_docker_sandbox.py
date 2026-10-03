"""Real isolation tests. Skipped automatically when Docker or the sandbox image is missing.
Build the image first: redtogreen sandbox-build"""

import os

import pytest

from redtogreen.sandbox.docker_sandbox import DockerSandbox

from .conftest import docker_ready

pytestmark = [pytest.mark.docker, pytest.mark.skipif(not docker_ready(), reason="Docker sandbox image not available")]


@pytest.fixture
def sandbox(settings):
    return DockerSandbox(settings.model_copy(update={"sandbox_backend": "docker", "sandbox_timeout_s": 15}))


def run_py(sandbox, tmp_path, code: str):
    ws = tmp_path / "job" / "repo"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "probe.py").write_text(code)
    return sandbox.run_tests(ws, "python probe.py")


def test_happy_path(sandbox, mini_repo, tmp_path):
    result = sandbox.run_tests(mini_repo, "python -m pytest -q -p no:cacheprovider")
    assert not result.passed and "test_add" in result.output


def test_no_network(sandbox, tmp_path):
    r = run_py(sandbox, tmp_path, "import socket\ntry:\n socket.create_connection(('1.1.1.1', 443), 3)\n"
                                  " print('OPEN')\nexcept OSError as e:\n print('BLOCKED', e)\n")
    assert "BLOCKED" in r.output and "OPEN" not in r.output.replace("BLOCKED", "")


def test_no_host_secrets(sandbox, tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_should_not_leak")
    r = run_py(sandbox, tmp_path, "import os\nprint(sorted(os.environ))\nprint(os.environ.get('GITHUB_TOKEN'))")
    assert "ghp_should_not_leak" not in r.output


def test_code_is_read_only_and_user_is_not_root(sandbox, tmp_path):
    code = ("import os\nprint('uid', os.getuid())\n"
            "try:\n open('probe.py','w').write('x')\n print('WROTE')\nexcept OSError:\n print('RO')")
    r = run_py(sandbox, tmp_path, code)
    assert "uid 65534" in r.output and "RO" in r.output


def test_timeout_kills_infinite_loop(sandbox, tmp_path):
    r = run_py(sandbox, tmp_path, "while True: pass")
    assert r.timed_out and not r.passed and r.duration_s < 40


def test_process_limit(sandbox, tmp_path):
    code = ("import subprocess\nprocs=[]\ntry:\n for _ in range(1000):\n"
            "  procs.append(subprocess.Popen(['sleep','30']))\nexcept OSError as e:\n print('LIMITED', len(procs))\n")
    r = run_py(sandbox, tmp_path, code)
    assert "LIMITED" in r.output


def test_installs_requirements_then_runs_offline(sandbox, tmp_path):
    if os.environ.get("RTG_SKIP_PIP_TEST"):
        pytest.skip("no internet for pip in this environment")
    ws = tmp_path / "job" / "repo"
    ws.mkdir(parents=True)
    (ws / "requirements.txt").write_text("six\n")
    (ws / "probe.py").write_text("import six\nprint('six', six.__version__)\n")
    sandbox.prepare(ws)
    assert "six" in sandbox.run_tests(ws, "python probe.py").output
