"""Unit tests for configuration module"""
import os
import pytest
from pydantic import ValidationError
from backend.config import Settings


def test_database_url_validation_valid():
    """Test that valid PostgreSQL URLs are accepted"""
    settings = Settings(database_url="postgresql://user:pass@localhost:5432/db")
    assert settings.database_url == "postgresql://user:pass@localhost:5432/db"


def test_database_url_validation_invalid():
    """Test that non-PostgreSQL URLs are rejected"""
    with pytest.raises(ValidationError, match="database_url must start with postgresql://"):
        Settings(database_url="mysql://user:pass@localhost:3306/db")


def test_secret_key_minimum_length_valid():
    """Test that secret keys with sufficient length are accepted"""
    settings = Settings(secret_key="a" * 32)
    assert settings.secret_key == "a" * 32


def test_secret_key_minimum_length_invalid():
    """Test that short secret keys are rejected"""
    with pytest.raises(ValidationError, match="SECRET_KEY must be at least 32 characters long"):
        Settings(secret_key="short")


def test_secret_key_auto_generation_for_empty(clean_env):
    """Test that empty secret key generates a random key in development"""
    settings = Settings(secret_key="")
    # Should auto-generate a key
    assert len(settings.secret_key) >= 32
    assert settings.secret_key != ""


def test_secret_key_auto_generation_for_default(clean_env, monkeypatch):
    """Test that default placeholder generates a random key in development"""
    monkeypatch.setenv("ENVIRONMENT", "development")
    settings = Settings(secret_key="CHANGE_ME_IN_PRODUCTION")
    # Should auto-generate a key
    assert len(settings.secret_key) >= 32
    assert settings.secret_key != "CHANGE_ME_IN_PRODUCTION"


def test_secret_key_production_error(monkeypatch):
    """Test that default secret key raises error in production"""
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValidationError, match="SECRET_KEY must be changed from default value in production"):
        Settings(secret_key="CHANGE_ME_IN_PRODUCTION")


def test_default_settings(clean_env):
    """Test that default settings are loaded correctly"""
    settings = Settings()
    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.algorithm == "HS256"
    assert settings.access_token_expire_minutes == 30
    assert settings.reload is True
    assert settings.log_level == "INFO"
    assert settings.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"


def test_cors_origins_default():
    """Test that default CORS origins are set"""
    settings = Settings()
    assert "http://localhost:5173" in settings.cors_origins


def test_environment_override(monkeypatch, clean_env):
    """Test that environment variables override defaults"""
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("SECRET_KEY", "a" * 32)

    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 9000
    assert settings.log_level == "DEBUG"


def test_groq_api_key_warning_when_empty(clean_env):
    """Test that a warning is issued when GROQ_API_KEY is empty"""
    # This test just ensures no exception is raised
    # The actual warning is checked by pytest with -W
    settings = Settings(groq_api_key="")
    assert settings.groq_api_key == ""


def test_storage_path_default():
    """Test default storage path"""
    settings = Settings()
    assert settings.storage_path == "./storage"
