"""Tariff-specific LLM configuration."""
from backend.core.llm.provider import LLMProvider

DEFAULT_TARIFF_LLM_MODEL_GROQ = "openai/gpt-oss-20b"
DEFAULT_TARIFF_LLM_MODEL_CEREBRAS = "gpt-oss-120b"

# Legacy alias — kept for backward compatibility with existing references
DEFAULT_TARIFF_LLM_MODEL = DEFAULT_TARIFF_LLM_MODEL_GROQ


def get_tariff_llm_model() -> str:
    """Return the primary model identifier for the active provider."""
    from backend.config import settings
    if settings.llm_provider == "cerebras":
        return DEFAULT_TARIFF_LLM_MODEL_CEREBRAS
    if settings.llm_provider == "gemini":
        return settings.gemini_primary_model
    return DEFAULT_TARIFF_LLM_MODEL_GROQ


def get_tariff_llm_provider() -> LLMProvider:
    """Return an LLMProvider instance for the active provider."""
    from backend.config import settings
    if settings.llm_provider == "cerebras":
        from backend.core.llm.cerebras import CerebrasProvider
        return CerebrasProvider()
    if settings.llm_provider == "gemini":
        from backend.core.llm.gemini import GeminiProvider
        return GeminiProvider()
    from backend.core.llm.groq import GroqProvider
    return GroqProvider()
