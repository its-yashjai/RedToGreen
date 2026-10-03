from redtogreen.config import Settings
from redtogreen.llm.base import LLM


def get_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "anthropic":
        from redtogreen.llm.anthropic_llm import AnthropicLLM

        return AnthropicLLM(settings)
    if settings.llm_provider == "openai_compat":
        from redtogreen.llm.openai_compat import OpenAICompatLLM

        return OpenAICompatLLM(settings)
    raise ValueError("LLM_PROVIDER=fake has no real model; pass an LLM object explicitly (tests only).")
