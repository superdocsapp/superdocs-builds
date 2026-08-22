"""
Pins the fix for the second real bug found in production use (2026-08-22): verification correctly reported
success on the LOCALLY repaired html, but export() pulled the AI's original, uncorrected content from the
server-side session, because nothing ever pushed the repair back to the server. The exported file silently
contained the wrong content despite every internal check passing.
"""
from src.adaptation import run_adaptation
from src.chunk_classifier import protected_ids
from src.fake_client import FakeSuperDocsClient, corrupting_transform
from tests.fixtures import SAMPLE_CHAPTER_HTML


def test_export_after_repair_reflects_repaired_content_not_raw_ai_output():
    client = FakeSuperDocsClient()
    protected = set(protected_ids(SAMPLE_CHAPTER_HTML))
    # AI corrupts the equation chunk (c7) -- run_adaptation's repair step fixes this LOCALLY (result.html).
    client.script_edit("Rewrite the prose", corrupting_transform(protected, corrupt_chunk_id="c7"))

    result = run_adaptation(client, "source-1", SAMPLE_CHAPTER_HTML, "lower_reading_level")
    assert result.verification.ok
    assert "F = m × a" in result.html  # locally repaired content is correct

    # Before syncing: the server-side session (fake client's tracked state) still has the AI's raw,
    # uncorrected output from the chat() call -- this is the exact bug: verification passed, but this is
    # what a naive export() would have returned.
    exported_before_sync = client.export(result.session_id, fmt="docx").decode()
    assert "[simplified] F = m × a" in exported_before_sync, (
        "sanity check: without syncing, export reflects the AI's uncorrected output"
    )

    # The fix: explicitly push the repaired html back before exporting.
    client.load_html_as_document(result.session_id, result.html)
    exported_after_sync = client.export(result.session_id, fmt="docx").decode()
    assert "F = m × a" in exported_after_sync
    assert "[simplified] F = m × a" not in exported_after_sync, (
        "after syncing, export must reflect the REPAIRED equation, not the AI's rewritten version"
    )
