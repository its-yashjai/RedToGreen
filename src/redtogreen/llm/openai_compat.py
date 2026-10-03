"""Provider for any OpenAI-compatible Chat Completions API.

Works with Groq, Ollama (local), OpenRouter, Together, vLLM and Gemini's compat endpoint:
only LLM_BASE_URL, LLM_API_KEY and LLM_MODEL change.
"""

import json

from openai import AsyncOpenAI

from redtogreen.config import Settings
from redtogreen.llm.base import ToolCall, ToolResult, ToolSpec, Turn, price


class OpenAICompatConversation:
    def __init__(self, llm: "OpenAICompatLLM", system: str, user: str, tools: list[ToolSpec]):
        self.llm = llm
        self.messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        self.tools = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.input_schema},
            }
            for t in tools
        ]

    async def next_turn(self) -> Turn:
        response = await self.llm.client.chat.completions.create(
            model=self.llm.model,
            messages=self.messages,
            tools=self.tools or None,
            max_tokens=self.llm.max_tokens,
            temperature=0,
        )
        message = response.choices[0].message
        calls = []
        for tc in message.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
                error = "" if isinstance(args, dict) else "arguments must be a JSON object"
            except json.JSONDecodeError as exc:
                args, error = {}, f"invalid JSON arguments: {exc}"
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args, parse_error=error))

        # Keep the assistant message (including tool calls) in history, unchanged.
        entry: dict = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        self.messages.append(entry)

        usage = response.usage
        return Turn(
            text=message.content or "",
            tool_calls=calls,
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            stop_reason=response.choices[0].finish_reason or "",
        )

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            text = f"ERROR: {r.text}" if r.is_error else r.text
            self.messages.append({"role": "tool", "tool_call_id": r.call.id, "content": text})

    def add_user_message(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})


class OpenAICompatLLM:
    def __init__(self, settings: Settings):
        if not settings.llm_model:
            raise ValueError("Set LLM_MODEL to a tool-calling model from your provider.")
        self.model = settings.llm_model
        self.max_tokens = settings.llm_max_output_tokens
        self.settings = settings
        self.client = AsyncOpenAI(
            api_key=settings.llm_api_key or "not-needed",  # Ollama ignores the key
            base_url=settings.llm_base_url,
            max_retries=3,  # retries 429 / 5xx with backoff
        )

    def start(self, system: str, user: str, tools: list[ToolSpec]) -> OpenAICompatConversation:
        return OpenAICompatConversation(self, system, user, tools)

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        return price(
            input_tokens, output_tokens,
            self.settings.llm_price_input_per_mtok, self.settings.llm_price_output_per_mtok,
        )
