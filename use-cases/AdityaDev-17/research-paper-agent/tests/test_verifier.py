import json
from src.models import Section, Citation, SectionStatus, Source
from src.retrieval import RetrievalIndex
from src.verifier import verify_section


def fake_embed_fn(texts):
    return [[float(len(t)), 0.0, 0.0] for t in texts]


def make_selective_fake_llm(unsupported_claim_texts: set[str]):
    """Returns supported=False only for claims in the given set —
    lets us plant exactly one bad claim and verify it's the one caught."""
    def fake_llm_fn(system_prompt: str, user_prompt: str) -> str:
        is_unsupported = any(claim in user_prompt for claim in unsupported_claim_texts)
        return json.dumps({
            "supported": not is_unsupported,
            "reason": "planted unsupported claim" if is_unsupported else "matches passage",
        })
    return fake_llm_fn


def _build_index_with_one_source():
    index = RetrievalIndex(embedding_dim=3)
    source = Source(id="src-1", title="Test Source", raw_text="x" * 50)
    index.add_source(source, fake_embed_fn)
    return index, source.chunks[0].chunk_id


def test_verifier_catches_planted_unsupported_claim():
    index, chunk_id = _build_index_with_one_source()

    section = Section(id="s1", paper_id="p1", title="Introduction", order=1)
    section.citations = [
        Citation(id="c1", section_id="s1", source_id="src-1",
                 claim_text="RAG reduces hallucination in legal QA.",
                 passage_ref=chunk_id, verified=False),
        Citation(id="c2", section_id="s1", source_id="src-1",
                 claim_text="RAG was invented by aliens in 1997.",  # planted bad claim
                 passage_ref=chunk_id, verified=False),
    ]

    llm_fn = make_selective_fake_llm(unsupported_claim_texts={"RAG was invented by aliens in 1997."})

    findings = verify_section(section, index, llm_fn)

    assert len(findings) == 1
    assert findings[0]["citation_id"] == "c2"
    assert section.status == SectionStatus.FLAGGED

    # And the good claim really is marked verified, not swept up in the flag
    good_citation = next(c for c in section.citations if c.id == "c1")
    assert good_citation.verified is True
    bad_citation = next(c for c in section.citations if c.id == "c2")
    assert bad_citation.verified is False


def test_verifier_marks_section_verified_when_all_claims_pass():
    index, chunk_id = _build_index_with_one_source()

    section = Section(id="s1", paper_id="p1", title="Introduction", order=1)
    section.citations = [
        Citation(id="c1", section_id="s1", source_id="src-1",
                 claim_text="A true claim.", passage_ref=chunk_id, verified=False),
    ]

    llm_fn = make_selective_fake_llm(unsupported_claim_texts=set())  # nothing is unsupported

    findings = verify_section(section, index, llm_fn)

    assert findings == []
    assert section.status == SectionStatus.VERIFIED