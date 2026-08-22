from src.adaptation import run_adaptation, verify_protected_chunks
from src.chunk_classifier import classify_document, protected_ids
from src.fake_client import FakeSuperDocsClient, default_simplify_transform, corrupting_transform
from tests.fixtures import SAMPLE_CHAPTER_HTML


def test_well_behaved_adaptation_preserves_protected_chunks():
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    assert protected == {"c3", "c4", "c7", "c8", "c9"}, "sanity check on the fixture's classification"

    client.script_edit("Rewrite the prose", default_simplify_transform(protected))
    result = run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level")

    assert result.verification.ok
    assert result.verification.corrupted_chunk_ids == []

    # Prose chunks WERE changed (proves the adaptation actually did something, not a no-op).
    adapted_chunks = {c.chunk_id: c.text for c in classify_document(result.html)}
    assert "[simplified]" in adapted_chunks["c2"]
    assert "[simplified]" in adapted_chunks["c6"]

    # Protected chunks were NOT changed -- byte-identical, not just "looks similar".
    source_chunks = {c.chunk_id: c.html for c in classify_document(SAMPLE_CHAPTER_HTML)}
    for cid in protected:
        assert adapted_chunks_html(result.html, cid) == source_chunks[cid]


def adapted_chunks_html(html: str, chunk_id: str) -> str:
    from src.chunk_classifier import classify_document
    return next(c.html for c in classify_document(html) if c.chunk_id == chunk_id)


def test_misbehaving_ai_corruption_is_automatically_repaired_not_just_detected():
    """The AI (fake, here, but standing in for the real model's confirmed behavior of ignoring
    do-not-touch instructions) rewrites a protected chunk (the equation, c7) despite being told not to.
    Earlier design: run_adaptation would detect this and refuse to export. Current design (after real-API
    testing showed prompting alone isn't reliable): run_adaptation REPAIRS it automatically, so the final
    result is trustworthy without needing a human to manually retry. verify_protected_chunks on its own
    (tested separately, e.g. in test_verify_protected_chunks_flags_a_dropped_chunk) still proves detection
    works; this test proves the full pipeline delivers a correct result despite the AI's misbehavior."""
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    client.script_edit("Rewrite the prose", corrupting_transform(protected, corrupt_chunk_id="c7"))

    result = run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level")

    assert result.verification.ok, "the repair step should have fixed the corruption before verification ran"
    assert "F = m × a" in result.html, "the original equation content must be restored"


def test_only_prose_chunks_are_targeted_in_the_instruction():
    """The chat instruction sent to the AI must not ask it to touch protected content -- a defense-in-depth
    check alongside the hash verification, not a replacement for it."""
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    client.script_edit("Rewrite the prose", default_simplify_transform(protected))
    run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "language_learner")

    session_id, message = client.chat_log[0]
    assert "language" in message.lower() or "learner" in message.lower()
    assert "do not" in message.lower() or "non-protected" in message.lower()


def test_verify_protected_chunks_flags_a_dropped_chunk():
    """If an adapted document simply drops a protected chunk id entirely (not just modifies it), that must
    also register as a verification failure, not silently pass because 'nothing changed' at a missing id."""
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    adapted_missing_c9 = SAMPLE_CHAPTER_HTML.replace(
        '<div data-chunk-id="c9"><table><tr><td>Find acceleration</td><td>a = 12 / 6 = 2 m/s2</td></tr></table></div>', ""
    )
    result = verify_protected_chunks(SAMPLE_CHAPTER_HTML, adapted_missing_c9)
    assert not result.ok
    assert "c9" in result.corrupted_chunk_ids
