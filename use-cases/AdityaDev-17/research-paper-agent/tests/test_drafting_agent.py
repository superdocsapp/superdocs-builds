import json
from src.models import Section, Source
from src.retrieval import RetrievalIndex
from src.drafting_agent import draft_section
from src.mcp_client import FakeMCPClient


def fake_embed_fn(texts: list[str]) -> list[list[float]]:
    return [[float(len(t)), 0.0, 0.0] for t in texts]


def make_fake_llm(claims: list[dict]) -> callable:
    """Returns an llm_fn that ignores prompts and returns fixed claims —
    lets us control exactly what the 'model' says for each test case."""
    def fake_llm_fn(system_prompt: str, user_prompt: str) -> str:
        return json.dumps({"claims": claims})
    return fake_llm_fn


def test_draft_section_writes_grounded_content_and_citations():
    index = RetrievalIndex(embedding_dim=3)
    source = Source(id="src-1", title="Test Source", raw_text="x" * 50)
    index.add_source(source, fake_embed_fn)

    real_chunk_id = source.chunks[0].chunk_id
    chunk_id_to_source_id = {real_chunk_id: "src-1"}

    llm_fn = make_fake_llm([
        {"sentence": "RAG reduces hallucination in legal QA.", "supporting_chunk_id": real_chunk_id},
    ])

    mcp_client = FakeMCPClient()
    section = Section(id="s1", paper_id="p1", title="Introduction", order=1)

    draft_section(
        section=section,
        topic="RAG in legal QA",
        retrieval_index=index,
        embed_fn=fake_embed_fn,
        llm_fn=llm_fn,
        mcp_client=mcp_client,
        session_id="sess-1",
        chunk_id_to_source_id=chunk_id_to_source_id,
    )

    assert section.content == "RAG reduces hallucination in legal QA."
    assert section.content_hash != ""
    assert len(section.citations) == 1
    assert section.citations[0].source_id == "src-1"

    # Exactly one MCP call: edit_section
    assert len(mcp_client.calls) == 1
    call_name, args = mcp_client.calls[0]
    assert call_name == "edit_section"
    assert args["session_id"] == "sess-1"
    assert args["section_title"] == "Introduction"
    assert args["new_content"] == "RAG reduces hallucination in legal QA."


def test_draft_section_rejects_hallucinated_chunk_id():
    """If the LLM cites a chunk_id we never gave it, that's a hallucination
    and should fail loudly, not silently produce an ungrounded citation."""
    index = RetrievalIndex(embedding_dim=3)
    source = Source(id="src-1", title="Test Source", raw_text="x" * 50)
    index.add_source(source, fake_embed_fn)

    llm_fn = make_fake_llm([
        {"sentence": "Made up claim.", "supporting_chunk_id": "chunk-that-does-not-exist"},
    ])

    mcp_client = FakeMCPClient()
    section = Section(id="s1", paper_id="p1", title="Introduction", order=1)

    try:
        draft_section(
            section=section, topic="test", retrieval_index=index,
            embed_fn=fake_embed_fn, llm_fn=llm_fn, mcp_client=mcp_client,
            session_id="sess-1", chunk_id_to_source_id={},
        )
        assert False, "Expected a ValueError for hallucinated chunk_id"
    except ValueError:
        pass

    # And critically: no MCP call should have happened before the failure
    assert mcp_client.calls == []