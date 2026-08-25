"""Tests for Tariff LLM configuration."""
from unittest.mock import patch, MagicMock
from backend.modules.tariff.llm_config import (
    DEFAULT_TARIFF_LLM_MODEL,
    DEFAULT_TARIFF_LLM_MODEL_GROQ,
    DEFAULT_TARIFF_LLM_MODEL_CEREBRAS,
    get_tariff_llm_model,
    get_tariff_llm_provider,
)


def test_default_tariff_llm_model_alias():
    """Legacy alias still equals Groq model for backward compatibility."""
    assert DEFAULT_TARIFF_LLM_MODEL == "openai/gpt-oss-20b"


def test_get_tariff_llm_model_cerebras():
    """When LLM_PROVIDER=cerebras, returns Cerebras model."""
    mock_settings = MagicMock()
    mock_settings.llm_provider = "cerebras"
    with patch("backend.config.settings", mock_settings):
        model = get_tariff_llm_model()
    assert model == DEFAULT_TARIFF_LLM_MODEL_CEREBRAS
    assert model == "gpt-oss-120b"


def test_get_tariff_llm_model_groq():
    """When LLM_PROVIDER=groq, returns Groq model."""
    mock_settings = MagicMock()
    mock_settings.llm_provider = "groq"
    with patch("backend.config.settings", mock_settings):
        model = get_tariff_llm_model()
    assert model == DEFAULT_TARIFF_LLM_MODEL_GROQ
    assert model == "openai/gpt-oss-20b"


def test_get_tariff_llm_provider_cerebras():
    """When LLM_PROVIDER=cerebras, returns CerebrasProvider."""
    from backend.core.llm.cerebras import CerebrasProvider
    mock_settings = MagicMock()
    mock_settings.llm_provider = "cerebras"
    mock_settings.cerebras_api_key = "test-key"
    with patch("backend.config.settings", mock_settings):
        provider = get_tariff_llm_provider()
    assert isinstance(provider, CerebrasProvider)


def test_get_tariff_llm_provider_groq():
    """When LLM_PROVIDER=groq, returns GroqProvider."""
    from backend.core.llm.groq import GroqProvider
    mock_settings = MagicMock()
    mock_settings.llm_provider = "groq"
    mock_settings.groq_api_key = "test-key"
    with patch("backend.config.settings", mock_settings):
        provider = get_tariff_llm_provider()
    assert isinstance(provider, GroqProvider)
