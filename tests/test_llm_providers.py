"""Message-format tests for both providers, with the network call replaced by a fake."""

import asyncio
from types import SimpleNamespace as NS

import pytest

from redtogreen.llm.anthropic_llm import AnthropicLLM
from redtogreen.llm.base import LLMRefusal, ToolResult, ToolSpec
from redtogreen.llm.openai_compat import OpenAICompatLLM

TOOLS = [ToolSpec("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}})]


def test_openai_compat_round_trip(settings):
    llm = OpenAICompatLLM(settings.model_copy(update={"llm_model": "some-model", "llm_price_input_per_mtok": 1.0}))
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        tc = [NS(id="c1", function=NS(name="read_file", arguments='{"path": "a.py"}')),
              NS(id="c2", function=NS(name="read_file", arguments="{not json"))]
        return NS(choices=[NS(message=NS(content="", tool_calls=tc), finish_reason="tool_calls")],
                  usage=NS(prompt_tokens=1000, completion_tokens=50))

    llm.client = NS(chat=NS(completions=NS(create=create)))
    conv = llm.start("sys", "fix it", TOOLS)
    turn = asyncio.run(conv.next_turn())
    assert captured["tools"][0]["function"]["name"] == "read_file"
    assert turn.tool_calls[0].arguments == {"path": "a.py"}
    assert turn.tool_calls[1].parse_error.startswith("invalid JSON")
    conv.add_tool_results([ToolResult(turn.tool_calls[0], "content"), ToolResult(turn.tool_calls[1], "bad", True)])
    assert [m["role"] for m in conv.messages] == ["system", "user", "assistant", "tool", "tool"]
    assert conv.messages[-1]["content"].startswith("ERROR:")
    assert llm.cost_usd(1_000_000, 0) == 1.0


def anthropic_llm(settings, model="claude-opus-5-5"):
    return AnthropicLLM(settings.model_copy(update={"llm_model": model, "llm_api_key": "test"}))


def test_anthropic_round_trip(settings):
    llm = anthropic_llm(settings)
    captured = {}

    async def create(**kwargs):
        captured.update(kwargs)
        content = [NS(type="thinking", thinking=""), NS(type="text", text="Let me look."),
                   NS(type="tool_use", id="tu1", name="read_file", input={"path": "a.py"})]
        return NS(content=content, stop_reason="tool_use", stop_details=None,
                  usage=NS(input_tokens=1_000_000, output_tokens=0))

    llm.client = NS(beta=NS(messages=NS(create=create)))
    conv = llm.start("sys", "fix it", TOOLS)
    turn = asyncio.run(conv.next_turn())
    assert captured["fallbacks"] == "default" and captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["output_config"] == {"effort": "medium"}
    assert turn.text == "Let me look." and turn.tool_calls[0].name == "read_file"
    assert len(conv.messages[-1]["content"]) == 3  # thinking block kept unchanged in history
    conv.add_tool_results([ToolResult(turn.tool_calls[0], "content")])
    assert conv.messages[-1]["content"][0]["tool_use_id"] == "tu1"
    assert llm.cost_usd(1_000_000, 0) == 4.0


def test_anthropic_refusal(settings):
    llm = anthropic_llm(settings)

    async def create(**kwargs):
        return NS(content=[], stop_reason="refusal", stop_details=NS(category="cyber"),
                  usage=NS(input_tokens=1, output_tokens=0))

    llm.client = NS(beta=NS(messages=NS(create=create)))
    with pytest.raises(LLMRefusal, match="cyber"):
        asyncio.run(llm.start("s", "u", TOOLS).next_turn())


def test_no_fallbacks_for_models_without_support(settings):
    assert anthropic_llm(settings, "claude-haiku-4-5").use_fallbacks is False
