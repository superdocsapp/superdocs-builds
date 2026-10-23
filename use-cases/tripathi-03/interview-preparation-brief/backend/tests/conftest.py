"""Shared pytest fixtures — mocked LLM / no live API keys required."""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

# Ensure settings never require real credentials during collection/import.
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key-not-real")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key-not-real")
os.environ.setdefault("GROQ_API_KEY", "test-groq-key-not-real")
os.environ.setdefault("LLM_PROVIDER", "openai")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/interview_prep_test",
)
os.environ.setdefault("EVIDENCE_FALLBACK", "No evidence found.")


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key-not-real")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key-not-real")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key-not-real")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("EVIDENCE_FALLBACK", "No evidence found.")
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_embedding_vector() -> list[float]:
    from app.core.config import get_settings

    dims = get_settings().embedding_dimensions
    return [0.01] * dims


@pytest.fixture
def mock_embeddings(monkeypatch: pytest.MonkeyPatch, fake_embedding_vector: list[float]):
    """Patch EmbeddingService so no OpenAI embedding calls are made."""

    async def _embed_texts(self, texts: list[str]) -> list[list[float]]:  # noqa: ANN001
        return [fake_embedding_vector[:] for _ in texts]

    async def _embed_query(self, query: str) -> list[float]:  # noqa: ANN001
        return fake_embedding_vector[:]

    def _init(self) -> None:  # noqa: ANN001
        from app.core.config import get_settings

        self.settings = get_settings()
        self.provider = "local"
        self._openai = None
        self._gemini_model = None

    monkeypatch.setattr("app.services.rag.embeddings.EmbeddingService.__init__", _init)
    monkeypatch.setattr("app.services.rag.embeddings.EmbeddingService.embed_texts", _embed_texts)
    monkeypatch.setattr("app.services.rag.embeddings.EmbeddingService.embed_query", _embed_query)
    return True


@pytest.fixture
def mock_llm(monkeypatch: pytest.MonkeyPatch):
    """
    Patch invoke_structured / invoke_text to return deterministic fixtures.
    Override via mock_llm.set_structured(schema_name, payload).
    """

    store: dict[str, Any] = {}

    async def _invoke_structured(
        *,
        schema: type[BaseModel],
        system: str,
        user: str,
        temperature: float = 0.0,
    ):
        key = schema.__name__
        if key in store:
            payload = store[key]
            if isinstance(payload, schema):
                return payload
            if callable(payload):
                result = payload(system=system, user=user)
                return result if isinstance(result, schema) else schema.model_validate(result)
            return schema.model_validate(payload)
        if key == "QuestionCategoryLLMOutput":
            from app.schemas.questions import (
                NO_EVIDENCE,
                Difficulty,
                InterviewQuestionItem,
                QuestionCategoryLLMOutput,
                RevisionLink,
            )

            return QuestionCategoryLLMOutput(
                questions=[
                    InterviewQuestionItem(
                        question="Mock categorized interview question",
                        difficulty=Difficulty.MEDIUM,
                        expected_answer="Describe approach with trade-offs.",
                        resume_evidence=NO_EVIDENCE,
                        missing_knowledge=["Depth in topic"],
                        revision_links=[
                            RevisionLink(
                                title="Revise topic",
                                url="https://revise.local/topic/overview",
                            )
                        ],
                    )
                ]
            )
        return schema.model_validate({})

    async def _invoke_text(*, system: str, user: str, temperature: float = 0.0) -> str:
        if "invoke_text" in store:
            value = store["invoke_text"]
            return value(system=system, user=user) if callable(value) else str(value)
        return "No evidence found."

    targets = [
        "app.agents.llm.invoke_structured",
        "app.agents.llm.invoke_text",
        "app.services.questions.generator.invoke_structured",
        "app.services.company.company_research.invoke_structured",
        "app.services.resume.analyzer.invoke_structured",
        "app.agents.nodes.jd_parser.invoke_structured",
        "app.agents.nodes.skill_gap_analysis.invoke_structured",
        "app.agents.nodes.interview_preparation_report.invoke_structured",
        "app.agents.nodes.answer_generation.invoke_structured",
        "app.agents.nodes.answer_generation.invoke_text",
    ]
    for target in targets:
        attr = target.rsplit(".", 1)[-1]
        monkeypatch.setattr(
            target,
            _invoke_structured if attr == "invoke_structured" else _invoke_text,
            raising=False,
        )

    helper = MagicMock()
    helper.store = store
    helper.set_structured = lambda schema_name, payload: store.__setitem__(schema_name, payload)
    helper.set_text = lambda payload: store.__setitem__("invoke_text", payload)
    return helper


@pytest.fixture
def sample_resume() -> str:
    return (
        "Jane Doe\n"
        "Software Engineer\n"
        "5+ years of experience in backend systems.\n"
        "Acme Corp â€” Software Engineer (2020-2024)\n"
        "Built payment APIs with FastAPI and PostgreSQL.\n"
        "Skills: Python, FastAPI, PostgreSQL, Docker\n"
    )


@pytest.fixture
def sample_jd() -> str:
    return (
        "Backend Engineer\n"
        "Requirements: Python, FastAPI, Kubernetes, PostgreSQL, system design.\n"
        "Responsibilities: build APIs, improve reliability, mentor engineers.\n"
    )

