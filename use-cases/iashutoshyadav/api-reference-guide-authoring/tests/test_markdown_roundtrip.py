"""Runs against FakeSuperDocsClient (byte-identical passthrough export) - proves this module's own
pipeline (upload -> styled export -> markdown export -> compare) is wired correctly. Does NOT prove
SuperDocs's real product preserves fidelity - that needs a live key, flagged explicitly in
markdown_roundtrip.py's own docstring, not silently assumed here."""

from app.markdown_roundtrip import round_trip_markdown
from app.superdocs_client import FakeSuperDocsClient

SAMPLE_MARKDOWN = """# API Reference: createWidget

Creates a new widget.

```python
import widgets

client = widgets.Client(api_key="...")
result = client.create_widget(name="my-widget")
```

Architecture:

![sequence diagram](./diagrams/create-widget-flow.png)

See also the [full reference](./reference.md).
"""


def test_round_trip_preserves_the_code_block_and_the_image_reference():
    client = FakeSuperDocsClient()

    result = round_trip_markdown(client, SAMPLE_MARKDOWN, session_id="rt-1")

    assert result.code_blocks_preserved
    assert result.image_refs_preserved
    assert result.fully_preserved
    assert len(result.original_code_blocks) == 1
    assert "import widgets" in result.original_code_blocks[0]
    assert result.original_image_refs == ["![sequence diagram](./diagrams/create-widget-flow.png)"]


def test_round_trip_result_reports_exact_content_not_just_a_boolean():
    """The pipeline must expose what it actually compared, not just pass/fail - a reviewer (or this
    project's own demo) needs to see the before/after, not take a boolean's word for it."""
    client = FakeSuperDocsClient()

    result = round_trip_markdown(client, SAMPLE_MARKDOWN, session_id="rt-2")

    assert result.original_code_blocks == result.round_tripped_code_blocks
    assert result.original_image_refs == result.round_tripped_image_refs
    assert result.original_markdown == SAMPLE_MARKDOWN


def test_a_document_with_no_code_or_images_still_reports_preserved_trivially():
    client = FakeSuperDocsClient()
    plain_markdown = "# Just a heading\n\nSome plain prose, nothing fancy.\n"

    result = round_trip_markdown(client, plain_markdown, session_id="rt-3")

    assert result.fully_preserved
    assert result.original_code_blocks == []
    assert result.original_image_refs == []


class _LanguageTagStrippingClient(FakeSuperDocsClient):
    """Simulates a real, specific finding from running this build against the live SuperDocs API: the
    code's own content survives a round-trip byte-for-byte, but the fence's language tag (```python ->
    ```) is stripped. Not a hypothetical edge case - this is what the real product actually did when
    checked (verify_real_api.py), captured here as a permanent regression check rather than left as a
    one-off observation that could silently stop being true (or silently start being worse) later."""

    def export_document(self, session_id: str, format: str = "markdown") -> str:
        content = super().export_document(session_id, format)
        return content.replace("```python\n", "```\n")


class _ExtraBlankLineBeforeClosingFenceClient(FakeSuperDocsClient):
    """Simulates a second, smaller real finding from the live product (2026-08-20): an extra blank line
    appears right before a code fence's closing ``` that wasn't in the original. Found by comparing exact
    newline counts (22 vs 23) after a visual anomaly in a real browser turned out to be a rendering-only
    artifact - this newline-count check was what actually confirmed a real difference existed."""

    def export_document(self, session_id: str, format: str = "markdown") -> str:
        content = super().export_document(session_id, format)
        return content.replace("```python\n", "```\n").replace("```\n\n", "\n```\n\n")


def test_a_real_finding_extra_blank_line_before_closing_fence_does_not_affect_content_preservation():
    """The extra blank line sits between the code's last line and the closing fence - outside the code
    itself. code_content_preserved must stay True (nothing a reader would copy-paste changed; the content
    comparison strips trailing whitespace before comparing), even though code_blocks_preserved correctly
    stays False (the fence text itself did change)."""
    client = _ExtraBlankLineBeforeClosingFenceClient()

    result = round_trip_markdown(client, SAMPLE_MARKDOWN, session_id="rt-6")

    assert result.code_blocks_preserved is False
    assert result.code_content_preserved is True
    assert result.image_refs_preserved is True


def test_a_real_finding_captured_as_a_permanent_check_language_tag_lost_but_code_content_intact():
    """This is the precise, honest signal this build reports: code_blocks_preserved is False (the fence
    changed), but code_content_preserved is True (nothing a reader would copy-paste actually changed). A
    single blunt boolean would either hide this real limitation or overstate it as total failure - neither
    is the honest answer."""
    client = _LanguageTagStrippingClient()

    result = round_trip_markdown(client, SAMPLE_MARKDOWN, session_id="rt-4")

    assert result.code_blocks_preserved is False
    assert result.code_content_preserved is True
    assert result.image_refs_preserved is True
    assert result.fully_preserved is False  # strict check correctly still fails


def test_a_browser_submitted_CRLF_original_is_not_falsely_reported_as_changed():
    """Regression test for a real bug found live on 2026-08-20: HTML <textarea> form submissions
    normalize line endings to CRLF regardless of what the user typed, but SuperDocs's markdown export
    returns LF-only. Comparing the two without normalizing first reported a false 'code content changed'
    for content a human reading the page would see as byte-identical. Every curl-based test during design
    used LF throughout and never caught this - only driving it through an actual browser form did."""
    client = FakeSuperDocsClient()
    crlf_markdown = SAMPLE_MARKDOWN.replace("\n", "\r\n")

    result = round_trip_markdown(client, crlf_markdown, session_id="rt-5")

    assert result.code_blocks_preserved
    assert result.code_content_preserved
    assert result.image_refs_preserved
    assert result.fully_preserved


def test_a_real_image_is_uploaded_and_its_real_url_replaces_the_placeholder_path():
    """Task card names 'images' as a surface this build should touch - previously the round trip only
    ever passed a placeholder path like './diagrams/foo.png' through as text, never uploading an actual
    image via SuperDocs's real image endpoint. Found during an audit against the actual card text on
    2026-08-20."""
    client = FakeSuperDocsClient()
    fake_png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20

    result = round_trip_markdown(
        client, SAMPLE_MARKDOWN, session_id="rt-image-1", uploaded_image=(fake_png_bytes, "image/png")
    )

    assert result.real_image_url is not None
    assert result.real_image_url.startswith("https://fake-superdocs-images.test/")
    # The real uploaded URL must actually be what got round-tripped - not just uploaded and ignored.
    assert result.real_image_url in result.original_markdown
    assert "./diagrams/create-widget-flow.png" not in result.original_markdown


class _SignedUrlRewritingClient(FakeSuperDocsClient):
    def export_document(self, session_id: str, format: str = "markdown") -> str:
        content = super().export_document(session_id, format)
        return content.replace(
            "https://storage.example/img/abc123.png",
            "https://storage.example/img/abc123.png?X-Goog-Signature=deadbeef&X-Goog-Expires=86400",
        )


def test_a_real_finding_signed_url_rewrite_does_not_count_as_the_image_changing():
    """Real finding from uploading an actual image through this round trip against the live API
    (2026-08-20): SuperDocs's export rewrote the stable embed URL into a time-limited signed URL (a
    Google Cloud Storage query string, X-Goog-Expires=86400 - 24 hours). image_refs_preserved correctly
    goes False (the exact string changed), but image_target_preserved must stay True - it's the same
    underlying image, only the signature/expiry query string differs, not something a reader would
    notice looking at the rendered document today."""
    client = _SignedUrlRewritingClient()
    markdown = "![diagram](https://storage.example/img/abc123.png)\n"

    result = round_trip_markdown(client, markdown, session_id="rt-signed-url")

    assert result.image_refs_preserved is False
    assert result.image_target_preserved is True
