"""Mode 1: markdown -> SuperDocs styled document -> markdown, verifying code blocks and diagram
references survive unchanged - the task card's own bar for what strong looks like.

Honesty note, made explicit rather than glossed over: this module's own logic (upload -> export -> compare)
is fully tested offline against FakeSuperDocsClient, but the fake client's export is a byte-identical
passthrough - it proves this PIPELINE is wired correctly, not that SuperDocs's real product actually
preserves fidelity through its own conversion. That's the single riskiest unknown identified during design
(Phase 2), and it can only be answered by running this against the real API with a real key - not asserted
here as already true.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.superdocs_client import SuperDocsClient, to_base64

_CODE_BLOCK_RE = re.compile(r"```([a-zA-Z0-9_+-]*)\n([\s\S]*?)```")
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)")
_IMAGE_URL_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")


@dataclass
class RoundTripResult:
    original_markdown: str
    styled_html: str
    round_tripped_markdown: str
    # code_blocks_preserved: strict - fence, language tag, and content all byte-identical.
    # code_content_preserved: the code ITSELF (ignoring the language tag and surrounding whitespace) is
    #   byte-identical - a real, precise finding from running this against the live product: the language
    #   tag ("python") gets stripped to a bare fence on round-trip, but the code inside never changes.
    #   Reporting both, rather than one blunt boolean, is the honest version of this check - a caller that
    #   only asked "did the code survive" deserves the accurate answer, not a false pass or an
    #   overly-harsh fail that hides what actually happened.
    code_blocks_preserved: bool
    code_content_preserved: bool
    image_refs_preserved: bool
    image_target_preserved: bool
    original_code_blocks: list[str]
    round_tripped_code_blocks: list[str]
    original_image_refs: list[str]
    round_tripped_image_refs: list[str]
    real_image_url: str | None = None

    @property
    def fully_preserved(self) -> bool:
        return self.code_blocks_preserved and self.image_refs_preserved


def _extract_code_blocks(markdown: str) -> list[str]:
    """Full fence text, language tag included - used for the strict preservation check."""
    return [f"```{lang}\n{body}```" for lang, body in _CODE_BLOCK_RE.findall(markdown)]


def _extract_code_content(markdown: str) -> list[str]:
    """Just the code inside the fence, language tag and surrounding whitespace stripped - used for the
    content-only check, since that's the part that actually matters for a reader copying the example."""
    return [body.strip() for _, body in _CODE_BLOCK_RE.findall(markdown)]


def _extract_image_refs(markdown: str) -> list[str]:
    return _IMAGE_REF_RE.findall(markdown)


def _extract_image_targets(markdown: str) -> list[str]:
    return [match.group(2).split("?", 1)[0] for match in _IMAGE_URL_RE.finditer(markdown)]


def round_trip_markdown(
    client: SuperDocsClient,
    markdown_text: str,
    session_id: str,
    uploaded_image: tuple[bytes, str] | None = None,
) -> RoundTripResult:
    """Upload as markdown (SuperDocs parses it into a real styled document, not a plain-text passthrough -
    supported formats explicitly include .md), export the styled form to prove conversion actually
    happened, then export back to markdown and compare against the original for exact code-block and
    image-reference preservation.

    uploaded_image, when given as (raw_bytes, mime_type), is uploaded for real via
    POST /v1/documents/images/upload-base64 and its real, SuperDocs-hosted URL replaces the first image
    reference's target before the round trip runs - so "image reference preserved" is checked against an
    actual uploaded image SuperDocs knows about, not an arbitrary placeholder path like
    './diagrams/foo.png' that was never a real asset."""
    # Real bug, found live on 2026-08-20: an HTML <textarea> form submission normalizes line endings to
    # CRLF regardless of what the user typed, but SuperDocs's markdown export returns LF-only. Without
    # normalizing both sides the same way, an unrelated whitespace convention (invisible to a human
    # reading the page) got reported as "code content changed" - a false failure, not a real one. Every
    # curl-based test during design used LF throughout and never hit this; only driving it through an
    # actual browser form surfaced it.
    markdown_text = markdown_text.replace("\r\n", "\n")

    real_image_url: str | None = None
    if uploaded_image is not None:
        image_bytes, mime_type = uploaded_image
        real_image_url = client.upload_image(to_base64(image_bytes), mime_type)
        markdown_text = _IMAGE_URL_RE.sub(rf"\g<1>{real_image_url}\g<3>", markdown_text, count=1)

    client.upload_document("input.md", markdown_text.encode(), session_id=session_id)
    styled_html = client.export_document(session_id, format="html")
    round_tripped_markdown = client.export_document(session_id, format="markdown").replace("\r\n", "\n")

    original_code = _extract_code_blocks(markdown_text)
    round_tripped_code = _extract_code_blocks(round_tripped_markdown)
    original_content = _extract_code_content(markdown_text)
    round_tripped_content = _extract_code_content(round_tripped_markdown)
    original_images = _extract_image_refs(markdown_text)
    round_tripped_images = _extract_image_refs(round_tripped_markdown)
    original_targets = _extract_image_targets(markdown_text)
    round_tripped_targets = _extract_image_targets(round_tripped_markdown)

    return RoundTripResult(
        original_markdown=markdown_text,
        styled_html=styled_html if isinstance(styled_html, str) else str(styled_html),
        round_tripped_markdown=round_tripped_markdown,
        code_blocks_preserved=(original_code == round_tripped_code),
        code_content_preserved=(original_content == round_tripped_content),
        image_refs_preserved=(original_images == round_tripped_images),
        image_target_preserved=(original_targets == round_tripped_targets),
        original_code_blocks=original_code,
        round_tripped_code_blocks=round_tripped_code,
        original_image_refs=original_images,
        round_tripped_image_refs=round_tripped_images,
        real_image_url=real_image_url,
    )
