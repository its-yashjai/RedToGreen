"""Provider for Claude through the official Anthropic SDK (Messages API, manual tool loop).

A manual loop (instead of the SDK's tool runner) because the agent graph needs to own
every step: count steps, trace each tool call, and stop at the step budget.
"""

import anthropic

from redtogreen.config import Settings
from redtogreen.llm.base import LLMRefusal, ToolCall, ToolResult, ToolSpec, Turn, price

# USD per 1M tokens (input, output) for current models. Override with LLM_PRICE_* env vars.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
# Models that accept server-side refusal fallbacks (`fallbacks: "default"`).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicConversation:
    def __init__(self, llm: "AnthropicLLM", system: str, user: str, tools: list[ToolSpec]):
        self.llm = llm
        self.system = system
        self.messages: list = [{"role": "user", "content": user}]
        self.tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools
        ]

    async def next_turn(self) -> Turn:
        kwargs = {
            "model": self.llm.model,
            "max_tokens": self.llm.max_tokens,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
            "output_config": {"effort": self.llm.effort},
        }
        if self.llm.use_fallbacks:
            # If a safety classifier declines, the API retries on Anthropic's recommended model.
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        response = await self.llm.client.beta.messages.create(**kwargs)

        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None) if response.stop_details else None
            raise LLMRefusal(f"model declined the request (category: {category})")

        # Append the full content unchanged (thinking + text + tool_use blocks). The history is
        # append-only: earlier turns are never edited.
        self.messages.append({"role": "assistant", "content": response.content})

        calls, texts = [], []
        for block in response.content:
            if block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                calls.append(ToolCall(id=block.id, name=block.name, arguments=args))
            elif block.type == "text":
                texts.append(block.text)

        return Turn(
            text="\n".join(texts),
            tool_calls=calls,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            stop_reason=response.stop_reason or "",
            extra={"request_id": getattr(response, "_request_id", None)},
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        # All results for one assistant turn go back in a single user message.
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.call.id, "content": r.text, "is_error": r.is_error}
                for r in results
            ],
        })

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


class AnthropicLLM:
    def __init__(self, settings: Settings):
        self.model = settings.llm_model or DEFAULT_MODEL
        self.max_tokens = settings.llm_max_output_tokens
        self.effort = settings.anthropic_effort
        self.use_fallbacks = settings.anthropic_fallbacks and self.model in FALLBACK_MODELS
        self.settings = settings
        # With no explicit key the SDK reads ANTHROPIC_API_KEY (or an `ant auth login` profile).
        if settings.llm_api_key:
            self.client = anthropic.AsyncAnthropic(api_key=settings.llm_api_key, max_retries=3)
        else:
            self.client = anthropic.AsyncAnthropic(max_retries=3)

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> AnthropicConversation:
        return AnthropicConversation(self, system, user, tools)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        if self.settings.llm_price_input_per_mtok or self.settings.llm_price_output_per_mtok:
            p_in, p_out = self.settings.llm_price_input_per_mtok, self.settings.llm_price_output_per_mtok
        else:
            p_in, p_out = PRICES.get(self.model, (0.0, 0.0))
        return price(input_tokens, output_tokens, p_in, p_out)
