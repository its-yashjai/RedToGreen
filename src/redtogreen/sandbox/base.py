from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_OUTPUT_CHARS = 12_000


@dataclass
class RunResult:
    passed: bool
    exit_code: int
    output: str
    duration_s: float
    timed_out: bool = False

    def summary(self, max_chars: int = 6000) -> str:
        """The part of the output worth showing to the LLM: the end, where pytest prints failures."""
        status = "PASSED" if self.passed else ("TIMED OUT" if self.timed_out else "FAILED")
        text = self.output
        if len(text) > max_chars:
            text = "... (output truncated) ...\n" + text[-max_chars:]
        return f"Tests {status} (exit code {self.exit_code}, {self.duration_s:.1f}s)\n{text}"


def clip(text: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    return text if len(text) <= limit else text[: limit // 4] + "\n...\n" + text[-(limit * 3 // 4) :]


class Sandbox(Protocol):
    def prepare(self, workspace: Path) -> str:
        """Install the project's dependencies (if any). Returns a short log."""
        ...

    def run_tests(self, workspace: Path, command: str) -> RunResult:
        """Run the test command against the workspace and report the result."""
        ...
