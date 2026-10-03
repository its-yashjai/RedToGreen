"""Runs tests as a plain subprocess. NOT isolated: use only for development and unit tests.

It still applies the cheap protections: a timeout and an empty environment (no secrets).
"""

import os
import shlex
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

from redtogreen.config import Settings
from redtogreen.sandbox.base import RunResult, clip


class LocalSandbox:
    def __init__(self, settings: Settings):
        self.settings = settings
        warnings.warn("LocalSandbox is not isolated; use SANDBOX_BACKEND=docker for real runs.", stacklevel=2)

    def prepare(self, workspace: Path) -> str:
        return "local sandbox: using the current Python environment, nothing installed"

    def run_tests(self, workspace: Path, command: str) -> RunResult:
        args = shlex.split(command)
        if args and args[0] == "python":
            args[0] = sys.executable  # use the interpreter we are running in
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": tempfile.gettempdir(),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(workspace),
        }
        start = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
                timeout=self.settings.sandbox_timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
            return RunResult(False, -1, clip(out + "\n[killed: timeout]"), time.monotonic() - start, True)
        return RunResult(
            passed=proc.returncode == 0,
            exit_code=proc.returncode,
            output=clip(proc.stdout + proc.stderr),
            duration_s=time.monotonic() - start,
        )
