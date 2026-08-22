"""
Pins the fix for the real behavior found running against the live API on 2026-08-22: even given an
explicit chunk-id 'do not touch' list, the model still rewrote a figure caption's wording on every single
test run. repair_protected_chunks makes preservation a guarantee this code enforces, not a request the
model can decline.
"""
from src.adaptation import repair_protected_chunks, verify_protected_chunks, run_adaptation
from src.chunk_classifier import protected_ids
from src.fake_client import FakeSuperDocsClient
from tests.fixtures import SAMPLE_CHAPTER_HTML


def _reassign_ids_and_reword_caption(html: str) -> str:
    """Mirrors exactly what the real API did: reassigns every chunk id AND rewords the figure caption
    (c4) despite it being on the protected/do-not-touch list."""
    import re
    html = re.sub(r'data-chunk-id="([^"]*)"', lambda m: f'data-chunk-id="new-{m.group(1)}"', html)
    html = html.replace(
        "Figure 4.1: A free-body diagram showing the forces acting on a book resting on a table.",
        "Figure 4.1: This diagram shows the forces on a book on a table. Gravity pulls it down and the table pushes it up.",
    )
    return html


def test_repair_restores_a_rewritten_caption_to_byte_identical():
    corrupted_by_real_model = _reassign_ids_and_reword_caption(SAMPLE_CHAPTER_HTML)

    # Before repair: verification correctly reports the caption as corrupted (this is the exact real bug).
    pre_repair = verify_protected_chunks(SAMPLE_CHAPTER_HTML, corrupted_by_real_model)
    assert not pre_repair.ok
    assert "c4" in pre_repair.corrupted_chunk_ids

    # After repair: the caption is forcibly restored, verification now passes.
    repaired_html, unrepairable = repair_protected_chunks(SAMPLE_CHAPTER_HTML, corrupted_by_real_model)
    assert unrepairable == []
    post_repair = verify_protected_chunks(SAMPLE_CHAPTER_HTML, repaired_html)
    assert post_repair.ok, f"repair should have fixed everything, still corrupted: {post_repair.corrupted_chunk_ids}"

    assert "A free-body diagram showing the forces" in repaired_html, "original caption wording must be back"
    assert "This diagram shows the forces on a book" not in repaired_html, "the model's rewritten version must be gone"


def test_repair_leaves_genuinely_untouched_prose_alone():
    """Repair must only touch PROTECTED chunk positions -- prose edits the adaptation legitimately made
    must survive repair untouched."""
    corrupted_by_real_model = _reassign_ids_and_reword_caption(SAMPLE_CHAPTER_HTML)
    # Also simulate a legitimate prose simplification at c2, which should NOT be reverted by repair.
    simplified_and_corrupted = corrupted_by_real_model.replace(
        "A force is a push or a pull that acts on an object as a result of its interaction with another object.",
        "A force is simply a push or a pull.",
    )
    repaired_html, _ = repair_protected_chunks(SAMPLE_CHAPTER_HTML, simplified_and_corrupted)
    assert "A force is simply a push or a pull." in repaired_html, "legitimate prose simplification must survive repair"


def test_run_adaptation_end_to_end_with_a_misbehaving_fake_ai_still_produces_verified_output():
    """Full pipeline test: even when the fake AI corrupts a protected chunk (simulating the real model's
    behavior), run_adaptation's repair step means the FINAL result still passes verification -- the
    build no longer just refuses to export, it actually delivers a correct adaptation."""
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))

    def misbehaving_transform(html: str) -> str:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(attrs={"data-chunk-id": True}):
            for text_node in tag.find_all(string=True):
                if text_node.strip():
                    # Rewrites EVERYTHING, including protected chunks -- worst case, matching real behavior.
                    text_node.replace_with(f"[rewritten] {text_node.strip()}")
        return str(soup)

    client.script_edit("Rewrite the prose", misbehaving_transform)
    result = run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level")

    assert result.verification.ok, (
        f"repair should have fixed the misbehaving AI's output, still corrupted: {result.verification.corrupted_chunk_ids}"
    )
    # Protected content is back to original wording.
    assert "F = m × a" in result.html
    assert "[rewritten] F = m × a" not in result.html
