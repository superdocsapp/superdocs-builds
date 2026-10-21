"""Screenplay-specific LLM configuration."""
from backend.core.llm.provider import LLMProvider


def get_screenplay_llm_model() -> str:
    """Return the primary model identifier for screenplay workflow based on settings."""
    from backend.config import settings
    if settings.llm_provider == "cerebras":
        return "gpt-oss-120b"
    if settings.llm_provider == "gemini":
        return settings.gemini_primary_model
    return "llama-3.1-8b-instant"


def get_screenplay_llm_provider() -> LLMProvider:
    """Return an LLMProvider instance based on application settings."""
    from backend.config import settings
    if settings.llm_provider == "cerebras":
        from backend.core.llm.cerebras import CerebrasProvider
        return CerebrasProvider()
    if settings.llm_provider == "gemini":
        from backend.core.llm.gemini import GeminiProvider
        return GeminiProvider()
    from backend.core.llm.groq import GroqProvider
    return GroqProvider()
