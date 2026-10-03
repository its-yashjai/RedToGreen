"""Records every step the agent takes: which node, which tool, tokens, time.

The trace answers "why did the agent change that line?" and gives the cost numbers.
In the CLI it stays in memory; in the server a `sink` also writes each step to Postgres.
"""

import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Step:
    attempt: int
    node: str
    tool: str = ""
    detail: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    ms: int = 0
    ok: bool = True


@dataclass
class Tracer:
    sink: Callable[[Step], None] | None = None
    steps: list[Step] = field(default_factory=list)

    def record(self, step: Step) -> None:
        self.steps.append(step)
        if self.sink:
            self.sink(step)

    @contextmanager
    def span(self, attempt: int, node: str, tool: str = ""):
        """Time a block of work; the block can fill in `step.detail`, tokens and `ok`."""
        step = Step(attempt=attempt, node=node, tool=tool)
        start = time.monotonic()
        try:
            yield step
        except Exception as exc:
            step.ok = False
            step.detail = (step.detail + f" | error: {exc}")[:2000]
            raise
        finally:
            step.ms = int((time.monotonic() - start) * 1000)
            self.record(step)

    @property
    def input_tokens(self) -> int:
        return sum(s.input_tokens for s in self.steps)

    @property
    def output_tokens(self) -> int:
        return sum(s.output_tokens for s in self.steps)
