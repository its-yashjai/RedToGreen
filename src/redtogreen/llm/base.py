"""Provider-neutral LLM interface.

Each provider has its own message format (Anthropic content blocks vs OpenAI chat messages).
A `Conversation` hides that, so the agent loop is the same code for every provider.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    parse_error: str = ""  # set when the model produced invalid JSON arguments


@dataclass
class ToolResult:
    call: ToolCall
    text: str
    is_error: bool = False


@dataclass
class Turn:
    """One model response."""

    text: str
    tool_calls: list[ToolCall]
    input_tokens: int
    output_tokens: int
    stop_reason: str
    extra: dict[str, Any] = field(default_factory=dict)


class LLMRefusal(Exception):
    """The model declined the request (e.g. a safety classifier)."""


class Conversation(Protocol):
    async def next_turn(self) -> Turn: ...

    def add_tool_results(self, results: list[ToolResult]) -> None: ...

    def add_user_message(self, text: str) -> None: ...


class LLM(Protocol):
    model: str

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> Conversation: ...

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float: ...


def price(input_tokens: int, output_tokens: int, in_per_mtok: float, out_per_mtok: float) -> float:
    return (input_tokens * in_per_mtok + output_tokens * out_per_mtok) / 1_000_000
