import json
from src.models import Paper, Section, Citation, SectionStatus, Source
from src.retrieval import RetrievalIndex
from src.mcp_client import FakeMCPClient
from src.revision_agent import revise_and_reverify_section, prove_only_target_section_changed


def fake_embed_fn(texts):
    return [[float(len(t)), 0.0, 0.0] for t in texts]


def _build_index_with_source(raw_text: str = "x" * 50):
    index = RetrievalIndex(embedding_dim=3)
    source = Source(id="src-1", title="Test Source", raw_text=raw_text)
    index.add_source(source, fake_embed_fn)
    return index, source.chunks[0].chunk_id


def test_revision_fixes_flagged_claim_and_reverifies_clean():
    index, chunk_id = _build_index_with_source()
    section = Section(id="s1", paper_id="p1", title="Introduction", order=1)
    section.citations = [
        Citation(id="c1", section_id="s1", source_id="src-1",
                 claim_text="Good claim.", passage_ref=chunk_id, verified=True),
        Citation(id="c2", section_id="s1", source_id="src-1",
                 claim_text="Bad claim.", passage_ref=chunk_id, verified=False),
    ]
    findings = [{"citation_id": "c2", "claim_text": "Bad claim.", "reason": "unsupported"}]

    def revision_llm_fn(sys_p, user_p):
        return json.dumps({"sentence": "Fixed claim.", "supporting_chunk_id": chunk_id})

    def verifier_llm_fn(sys_p, user_p):
        return json.dumps({"supported": True, "reason": "now grounded"})

    mcp_client = FakeMCPClient()

    remaining = revise_and_reverify_section(
        section, findings, "test topic", index, fake_embed_fn,
        revision_llm_fn, verifier_llm_fn, mcp_client,
        session_id="sess-1",
        chunk_id_to_source_id={chunk_id: "src-1"},
    )

    assert remaining == []
    assert section.status == SectionStatus.VERIFIED
    fixed = next(c for c in section.citations if c.id == "c2")
    assert fixed.claim_text == "Fixed claim."
    untouched = next(c for c in section.citations if c.id == "c1")
    assert untouched.claim_text == "Good claim."  # never touched

    # Exactly one MCP call: edit_section, with the reassembled full section content
    assert len(mcp_client.calls) == 1
    call_name, args = mcp_client.calls[0]
    assert call_name == "edit_section"
    assert args["new_content"] == "Good claim. Fixed claim."


def test_revision_touches_only_target_section_across_whole_paper():
    """This is the direct proof the card's strong-build criteria describes:
    revising one section must leave every other section byte-identical."""
    index, chunk_id = _build_index_with_source()

    paper = Paper(id="p1", topic="test topic")
    section_intro = Section(id="s1", paper_id="p1", title="Introduction", order=1)
    section_intro.set_content("Untouched intro content.")
    section_method = Section(id="s2", paper_id="p1", title="Method", order=2)
    section_method.citations = [
        Citation(id="c1", section_id="s2", source_id="src-1",
                 claim_text="Flagged claim.", passage_ref=chunk_id, verified=False),
    ]
    section_method.set_content("Flagged claim.")
    paper.sections = [section_intro, section_method]

    before = paper.snapshot_all_hashes()
    findings = [{"citation_id": "c1", "claim_text": "Flagged claim.", "reason": "unsupported"}]

    def revision_llm_fn(sys_p, user_p):
        return json.dumps({"sentence": "Corrected claim.", "supporting_chunk_id": chunk_id})

    def verifier_llm_fn(sys_p, user_p):
        return json.dumps({"supported": True, "reason": "grounded"})

    revise_and_reverify_section(
        section_method, findings, "test topic", index, fake_embed_fn,
        revision_llm_fn, verifier_llm_fn, FakeMCPClient(),
        session_id="sess-1",
        chunk_id_to_source_id={chunk_id: "src-1"},
    )

    # This call raises if anything other than s2 changed
    prove_only_target_section_changed(paper, before, target_section_id="s2")