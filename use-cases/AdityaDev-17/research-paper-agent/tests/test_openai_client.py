r"""These tests make REAL OpenAI API calls and cost real (tiny) money.
Not run as part of the normal `pytest tests\` sweep — run explicitly:

    pytest tests \test_openai_client.py -v -m real_api

Requires OPENAI_API_KEY to be set (via src.config, which loads .env).
"""
import pytest
from src.config import OPENAI_API_KEY
from src.openai_client import OpenAIClient, EMBEDDING_DIM


pytestmark = pytest.mark.real_api


def test_embed_fn_returns_correct_dimension():
    client = OpenAIClient(api_key=OPENAI_API_KEY)
    embeddings = client.embed_fn(["Retrieval-augmented generation reduces hallucination."])

    assert len(embeddings) == 1
    assert len(embeddings[0]) == EMBEDDING_DIM
    assert client.total_tokens > 0
    assert client.total_cost_usd > 0


def test_llm_fn_returns_valid_json_matching_drafting_schema():
    """Sanity check: does the real model actually return the exact JSON
    shape drafting_agent.py expects, given the real system prompt?"""
    client = OpenAIClient(api_key=OPENAI_API_KEY)

    system_prompt = (
        'You must respond with ONLY valid JSON in this exact shape: '
        '{"claims": [{"sentence": "...", "supporting_chunk_id": "..."}]}'
    )
    user_prompt = (
        "Source passages:\n"
        "[chunk-1] Retrieval-augmented generation combines a retriever with a generator "
        "to ground LLM outputs in external documents.\n\n"
        "Write one claim about what RAG does, citing chunk-1."
    )

    raw_response = client.llm_fn(system_prompt, user_prompt)

    import json
    parsed = json.loads(raw_response)  # will raise if not valid JSON — that's the point
    assert "claims" in parsed
    assert len(parsed["claims"]) >= 1
    assert parsed["claims"][0]["supporting_chunk_id"] == "chunk-1"