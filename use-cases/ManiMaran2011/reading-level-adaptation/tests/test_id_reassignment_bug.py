"""
Reproduces the real bug found running against the live SuperDocs API on 2026-08-22: chunk ids are NOT
stable across a chat turn -- SuperDocs reassigns them even for content it didn't touch. An earlier version
of verify_protected_chunks matched by chunk_id and reported every single protected chunk as corrupted,
even ones that were byte-identical, because the id it was looking for simply didn't exist anymore under
that name. These tests pin the fix: verification (and comparison) must work by CONTENT, not by id.
"""
from src.adaptation import verify_protected_chunks
from src.comparison import build_comparison, AdaptationResult
from src.adaptation import VerificationResult


def _reassign_all_ids(html: str, prefix: str) -> str:
    """Simulates what the real API does: every data-chunk-id in the document gets a brand new value,
    even though the actual visible content of most chunks is unchanged."""
    import re
    counter = [0]

    def _new_id(match):
        counter[0] += 1
        return f'data-chunk-id="{prefix}-{counter[0]}"'

    return re.sub(r'data-chunk-id="[^"]*"', _new_id, html)


SOURCE = """
<div data-chunk-id="orig-1"><h2>4.1 What is a Force?</h2></div>
<div data-chunk-id="orig-2"><p>A force is a push or a pull.</p></div>
<div data-chunk-id="orig-3"><p><i>Equation 4.1: F = m times a.</i></p></div>
"""


def test_verification_survives_full_id_reassignment_when_content_is_actually_unchanged():
    # Simulate: SuperDocs reprocesses the whole doc and reassigns every id, but doesn't actually touch the
    # equation's content -- only reality is the ids moved, not the protected text.
    reassigned_but_unchanged = _reassign_all_ids(SOURCE, "new")

    result = verify_protected_chunks(SOURCE, reassigned_but_unchanged)
    assert result.ok, (
        "content-based verification must NOT flag a protected chunk as corrupted just because its id "
        "changed -- this is the exact false-positive the real API run surfaced"
    )


def test_verification_still_catches_a_real_corruption_even_with_reassigned_ids():
    # Now actually corrupt the equation's text AS WELL as reassigning ids -- the real failure mode this
    # build exists to catch must still be caught even though ids are also different.
    reassigned = _reassign_all_ids(SOURCE, "new")
    actually_corrupted = reassigned.replace("F = m times a.", "F = m plus a.")  # wrong physics, injected

    result = verify_protected_chunks(SOURCE, actually_corrupted)
    assert not result.ok, "a genuine content change to a protected chunk must still be caught after id reassignment"


def test_comparison_view_aligns_by_position_when_ids_are_reassigned():
    reassigned_but_unchanged = _reassign_all_ids(SOURCE, "new")
    fake_result = AdaptationResult(
        adaptation_type="lower_reading_level", session_id="s1", html=reassigned_but_unchanged,
        verification=VerificationResult(ok=True, protected_chunk_ids=["orig-3"], corrupted_chunk_ids=[]),
    )
    rows = build_comparison(SOURCE, {"lower_reading_level": fake_result})
    protected_row = next(r for r in rows if r.kind == "protected")
    assert protected_row.unchanged_confirmed is True, (
        "comparison view must correctly show a protected chunk as unchanged even when its id was "
        "reassigned, as long as the content itself is identical"
    )
