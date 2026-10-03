"""LLMs that need no API key. Used by unit tests and by the benchmark's pipeline check.

ScriptedLLM: replays a fixed list of turns (unit tests).
OracleLLM:   knows the right fix (from the benchmark's bug definition) and applies it with the
             real tools. It proves the plumbing works end to end (MCP, sandbox, graph, guard),
             not that an AI can fix bugs. Never report oracle numbers as a fix rate.
"""

from dataclasses import dataclass

from redtogreen.llm.base import ToolCall, ToolResult, ToolSpec, Turn


class _ReplayConversation:
    def __init__(self, turns: list[Turn]):
        self.turns = list(turns)
        self.received: list[ToolResult] = []
        self.user_messages: list[str] = []

    async def next_turn(self) -> Turn:
        if not self.turns:
            return Turn("Done.", [], 0, 0, "end_turn")
        return self.turns.pop(0)

    def add_tool_results(self, results: list[ToolResult]) -> None:
        self.received.extend(results)

    def add_user_message(self, text: str) -> None:
        self.user_messages.append(text)


class ScriptedLLM:
    """Each call to start() pops the next script (one script per attempt)."""

    model = "scripted"

    def __init__(self, scripts: list[list[Turn]]):
        self.scripts = list(scripts)
        self.conversations: list[_ReplayConversation] = []
        self.prompts: list[str] = []

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> _ReplayConversation:
        self.prompts.append(user)
        conv = _ReplayConversation(self.scripts.pop(0) if self.scripts else [])
        self.conversations.append(conv)
        return conv

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0


@dataclass
class KnownFix:
    path: str
    old_text: str
    new_text: str


class OracleLLM:
    model = "oracle"

    def __init__(self, fixes: list[KnownFix]):
        self.fixes = fixes

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> _ReplayConversation:
        turns = []
        for i, fix in enumerate(self.fixes):
            turns.append(Turn("", [ToolCall(f"r{i}", "read_file", {"path": fix.path})], 0, 0, "tool_use"))
            turns.append(Turn("", [ToolCall(f"e{i}", "replace_in_file", {
                "path": fix.path, "old_text": fix.old_text, "new_text": fix.new_text,
            })], 0, 0, "tool_use"))
        turns.append(Turn("Root cause: a seeded bug. Fix: restored the correct code.", [], 0, 0, "end_turn"))
        return _ReplayConversation(turns)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return 0.0
