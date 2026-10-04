"""Runs the repo's tests inside a throwaway, locked-down Docker container.

Two phases:
  1. prepare(): install requirements.txt WITH network, but no secrets and no write access
     to the code (packages go to a separate /deps folder).
  2. run_tests(): run the tests with NO network, read-only code, CPU/memory/process limits,
     no Linux capabilities, a non-root user and a hard timeout. The container is deleted after.

Even if the code under test is malicious (or a prompt injection tricked the LLM),
there is nothing to steal (no secrets inside) and nowhere to send it (no network).
"""

import os
import time
from pathlib import Path

import docker
from docker.errors import ImageNotFound
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from redtogreen.config import Settings
from redtogreen.sandbox.base import RunResult, clip

NOBODY = "65534:65534"
LABEL = {"app": "redtogreen-sandbox"}


class DockerSandbox:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = docker.from_env()

    # ---------- helpers ----------
    def ensure_image(self) -> None:
        try:
            self.client.images.get(self.settings.sandbox_image)
        except ImageNotFound as exc:
            raise RuntimeError(
                f"Sandbox image '{self.settings.sandbox_image}' not found. "
                "Build it with: redtogreen sandbox-build"
            ) from exc

    @staticmethod
    def deps_dir(workspace: Path) -> Path:
        deps = workspace.parent / "deps"
        deps.mkdir(parents=True, exist_ok=True)
        os.chmod(deps, 0o777)  # the container runs as 'nobody' and must be able to write here
        return deps

    @staticmethod
    def make_readable(workspace: Path) -> None:
        """The container runs as 'nobody', so the job's copy must be world-readable. Machines with a
        strict umask (e.g. GitHub Codespaces) create files only their owner can read. The code is
        still mounted read-only, so this grants reading, never writing."""
        for root, dirs, files in os.walk(workspace):
            for name in dirs:
                path = os.path.join(root, name)
                if not os.path.islink(path):
                    os.chmod(path, os.stat(path).st_mode | 0o555)
            for name in files:
                path = os.path.join(root, name)
                if not os.path.islink(path):
                    os.chmod(path, os.stat(path).st_mode | 0o444)
        os.chmod(workspace, os.stat(workspace).st_mode | 0o555)

    def _hardening(self) -> dict:
        opts = {
            "user": NOBODY,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges"],
            "mem_limit": self.settings.sandbox_memory,
            "memswap_limit": self.settings.sandbox_memory,  # no swap escape hatch
            "nano_cpus": int(self.settings.sandbox_cpus * 1e9),
            "pids_limit": self.settings.sandbox_pids_limit,  # stops fork bombs
            "read_only": True,
            "tmpfs": {"/tmp": "rw,size=64m"},
            "labels": LABEL,
        }
        if self.settings.sandbox_runtime:
            opts["runtime"] = self.settings.sandbox_runtime  # e.g. gVisor's "runsc"
        return opts

    def _run(self, command: list[str], volumes: dict, network: str, env: dict, timeout: int) -> RunResult:
        self.ensure_image()
        start = time.monotonic()
        container = self.client.containers.run(
            self.settings.sandbox_image,
            command,
            detach=True,
            network_mode=network,
            volumes=volumes,
            working_dir="/workspace",
            environment=env,  # built from scratch: the host's secrets never get in
            **self._hardening(),
        )
        timed_out = False
        try:
            try:
                exit_code = container.wait(timeout=timeout)["StatusCode"]
            except (ReadTimeout, RequestsConnectionError):
                timed_out = True
                exit_code = -1
                container.kill()
            output = container.logs(stdout=True, stderr=True).decode(errors="replace")
        finally:
            container.remove(force=True)
        if timed_out:
            output += f"\n[killed: exceeded the {timeout}s sandbox timeout]"
        return RunResult(
            passed=exit_code == 0 and not timed_out,
            exit_code=exit_code,
            output=clip(output),
            duration_s=time.monotonic() - start,
            timed_out=timed_out,
        )

    # ---------- Sandbox interface ----------
    def prepare(self, workspace: Path) -> str:
        requirements = workspace / "requirements.txt"
        if not requirements.exists():
            return "no requirements.txt: nothing to install"
        deps = self.deps_dir(workspace)
        self.make_readable(workspace)
        result = self._run(
            ["python", "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check",
             "--target", "/deps", "-r", "/workspace/requirements.txt"],
            volumes={
                str(workspace): {"bind": "/workspace", "mode": "ro"},
                str(deps): {"bind": "/deps", "mode": "rw"},
            },
            network="bridge",  # installing needs the internet; running tests does not
            env={"HOME": "/tmp", "PIP_NO_INPUT": "1"},
            timeout=self.settings.sandbox_install_timeout_s,
        )
        if not result.passed:
            raise RuntimeError(f"Dependency install failed:\n{result.summary(3000)}")
        return f"installed requirements in {result.duration_s:.1f}s"

    def run_tests(self, workspace: Path, command: str) -> RunResult:
        deps = self.deps_dir(workspace)
        self.make_readable(workspace)
        return self._run(
            ["sh", "-c", command],
            volumes={
                str(workspace): {"bind": "/workspace", "mode": "ro"},  # tests cannot modify code
                str(deps): {"bind": "/deps", "mode": "ro"},
            },
            network="none",
            env={
                "HOME": "/tmp",
                "PYTHONPATH": "/workspace:/deps",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            timeout=self.settings.sandbox_timeout_s,
        )
