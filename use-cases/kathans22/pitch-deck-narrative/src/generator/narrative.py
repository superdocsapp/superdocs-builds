"""generate_narrative(vertical) — batched section fill from knowledge files.

Produces a speaking-script document (never a slide deck) for one vertical.
"""

from __future__ import annotations

import base64
import html
import logging
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2

from .format_guard import FormatGuardError, assert_not_deck
from .ledger import Ledger, ops_from_response, parse_ops_ceiling
from .manifest import load_deck_manifest, load_product, load_validated, project_root
from .mcp_client import (
    SuperDocsClient,
    SuperDocsClientError,
    chat_batch_cap,
    chunk_section_numbers,
    landed_check,
)

logger = logging.getLogger(__name__)

OUT_DIR = project_root() / "out"


def build_skeleton_html(
    manifest: dict[str, Any] | None = None,
    product: dict[str, Any] | None = None,
) -> str:
    """Build an empty nine-section speaking-script skeleton from the deck manifest."""
    manifest = manifest or load_deck_manifest()
    product_doc = product or load_product()
    product_block = product_doc.get("product") or product_doc
    product_name = html.escape(str(product_block.get("name", "ClarityDocs")))
    notice = html.escape(
        str(manifest.get("script_notice") or "Speaking script — not a slide deck.")
    )
    sections = manifest.get("sections") or []
    if not sections:
        raise ValueError("deck manifest has no sections — cannot build skeleton")

    parts: list[str] = [
        "<html><body>",
        f"<h1>{product_name} — Pitch Speaking Script</h1>",
        f"<p><strong>{notice}</strong></p>",
        "<p>Vertical: (to be filled). Each slide-equivalent below is a speaking "
        "section with a talking point and full speaker notes — not a slide canvas.</p>",
    ]
    for section in sections:
        number = int(section["number"])
        title = html.escape(str(section["title"]))
        parts.append(f"<h2>Slide-equivalent {number} — {title}</h2>")
        parts.append(
            f"<p><em>Talking point:</em> PLACEHOLDER_TALKING_POINT_{number}</p>"
        )
        parts.append(
            f"<p><em>Speaker notes:</em> PLACEHOLDER_SPEAKER_NOTES_{number}</p>"
        )
    parts.append("</body></html>")
    return "\n".join(parts)


def skeleton_pre_edit_bodies(manifest: dict[str, Any] | None = None) -> dict[int, str]:
    """Pre-edit fingerprint text for landed-check (placeholder bodies)."""
    manifest = manifest or load_deck_manifest()
    bodies: dict[int, str] = {}
    for section in manifest.get("sections") or []:
        number = int(section["number"])
        bodies[number] = (
            f"PLACEHOLDER_TALKING_POINT_{number} PLACEHOLDER_SPEAKER_NOTES_{number}"
        )
    return bodies


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def build_batch_instruction(
    product: dict[str, Any],
    vertical: dict[str, Any],
    sections: list[dict[str, Any]],
) -> str:
    """Instruction for one batch: draw substance from the vertical knowledge file."""
    product_block = product.get("product") or product
    product_name = _text(product_block.get("name"))
    positioning = _text(product_block.get("positioning"))
    capabilities = product_block.get("capabilities") or []
    differentiator = _text(product_block.get("differentiator"))
    terms = ", ".join(_text(t) for t in (vertical.get("terminology") or []))
    vertical_label = _text(vertical.get("display_name") or vertical.get("vertical"))

    section_blocks: list[str] = []
    for section in sections:
        number = int(section["number"])
        title = _text(section["title"])
        weight = section.get("weight")
        section_blocks.append(
            f"""
### Slide-equivalent {number} — {title} (weight: {weight})
- Keep the heading as: Slide-equivalent {number} — {title}
- Write one clear **Talking point** (one sentence the presenter says first).
- Write **full speaker notes** (multiple paragraphs — this is the product; not bullets-only).
- Replace PLACEHOLDER_TALKING_POINT_{number} and PLACEHOLDER_SPEAKER_NOTES_{number} completely.
  Those placeholder strings must not appear anywhere in the finished section.
- Do not invent a slide layout or anything confusable with a presentation file.
- Do not leave a second leftover Speaker notes / Talking point block under the real one.
""".strip()
        )

    return f"""
You are filling a SPEAKING SCRIPT document for {product_name} aimed at the
{vertical_label} vertical.

CRITICAL: This is a speaking script — not a slide deck. Never imply a presentation
file comes out. Use the label "slide-equivalent" only as a section name.

Product (held constant — do not reinvent the product):
- Name: {product_name}
- Positioning: {positioning}
- Capabilities: {"; ".join(_text(c) for c in capabilities)}
- Differentiator: {differentiator}

Vertical knowledge (substance — draw from this, do NOT use a generic industry template):
- Buyer role: {_text(vertical.get("buyer_role"))}
- Regulatory trigger: {_text(vertical.get("regulatory_trigger"))}
- Document pain: {_text(vertical.get("document_pain"))}
- Typical objection: {_text(vertical.get("typical_objection"))}
- Proof point: {_text(vertical.get("proof_point"))}
- Terminology to use naturally: {terms}

Fill ONLY these sections:
{chr(10).join(section_blocks)}

For shared-weight sections, keep product framing consistent but still write real notes.
For vertical-weight sections, the talking point and notes MUST reflect this vertical's
specific buyer, pain, objection, and proof — not a noun-swapped generic pitch.

COMPLIANCE (non-negotiable — task2-guidelines §5):
- Do not claim ClarityDocs or SuperDocs is certified (HIPAA, SOC 2, FERPA, COPPA, ISO, or any other).
- Regulatory names (HIPAA, SOC 2, FERPA, BSA/AML, ABA rules) are the buyer's context only — orientation, never a certification of this product.
- Do not write that a care pathway, export, or workflow "meets HIPAA … by design" or that the buyer "meets HIPAA" because they used the tool.
- Do not promise audited or guaranteed removal/redaction of personal data. Redaction is human-reviewed and must be said that way. Never "PHI redacted, of course".
""".strip()


def parse_script_sections(markdown: str) -> dict[int, str]:
    """Parse slide-equivalent section bodies from exported markdown."""
    bodies: dict[int, str] = {}
    pattern = re.compile(
        r"^##\s+Slide-equivalent\s+(\d+)[^\n]*\n(.*?)(?=^##\s+Slide-equivalent|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(markdown or ""):
        bodies[int(match.group(1))] = match.group(2).strip()
    return bodies


_SECTION_HEADING_RE = re.compile(
    r"(^##\s+Slide-equivalent\s+(\d+)[^\n]*\n)",
    re.MULTILINE,
)
_TALKING_POINT_LINE_RE = re.compile(
    r"(?im)^([*_]*talking point:?[*_]*[^\n]*\n)",
)
_IMG_SRC_RE = re.compile(
    r"!\[([^\]]*)\]\(([^)]+)\)|<img[^>]+src=['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SectionImageEmbed:
    """A generated supporting image to land in one slide-equivalent section."""

    section_number: int
    caption: str
    src: str
    alt: str | None = None


def presenter_visual_caption(detail: str) -> str:
    """Canonical caption: presenter support, never slide chrome."""
    from .imagegen import PRESENTER_VISUAL_MARKER

    detail = " ".join((detail or "").split()).strip().rstrip(".")
    if not detail:
        return PRESENTER_VISUAL_MARKER
    if detail.lower().startswith(PRESENTER_VISUAL_MARKER.lower()):
        return detail
    return f"{PRESENTER_VISUAL_MARKER}: {detail}"


def figure_markdown(embed: SectionImageEmbed) -> str:
    caption = presenter_visual_caption(embed.caption)
    alt = embed.alt or caption
    return f"![{alt}]({embed.src})\n\n*{caption}*\n"


def first_image_src(text: str) -> str | None:
    """First markdown or HTML image src in a section body, if any."""
    match = _IMG_SRC_RE.search(text or "")
    if not match:
        return None
    return (match.group(2) or match.group(3) or "").strip() or None


def embeds_from_generated_results(
    results: list[dict[str, Any]],
    markdown: str,
) -> list[SectionImageEmbed]:
    """Build section embeds from generate-image results + exported markdown srcs."""
    bodies = parse_script_sections(markdown)
    embeds: list[SectionImageEmbed] = []
    for row in results:
        if row.get("skipped") or not row.get("generated"):
            continue
        number = int(row["section_number"])
        body = bodies.get(number, "")
        src = first_image_src(body) or str(row.get("image_src") or "").strip()
        if not src:
            continue
        embeds.append(
            SectionImageEmbed(
                section_number=number,
                caption=str(row.get("reason") or row.get("title") or ""),
                src=src,
            )
        )
    return embeds


def _insert_figure_in_section(body: str, embed: SectionImageEmbed) -> str:
    from .imagegen import PRESENTER_VISUAL_MARKER, section_has_supporting_visual

    figure = figure_markdown(embed)
    if section_has_supporting_visual(body):
        if embed.src and embed.src in body:
            if PRESENTER_VISUAL_MARKER.lower() not in body.lower():
                return body.rstrip() + "\n\n" + f"*{presenter_visual_caption(embed.caption)}*\n"
            return body
        # Wrong place or missing src — still add a correctly captioned figure after TP.
    match = _TALKING_POINT_LINE_RE.search(body)
    if match:
        return body[: match.end()] + "\n" + figure + "\n" + body[match.end() :]
    return figure + "\n" + body


def embed_images_into_markdown(
    markdown: str,
    embeds: list[SectionImageEmbed],
) -> str:
    """Place each generated image in its slide-equivalent section with a caption.

    Inserts after the talking point (presenter reads notes around a visual), never
    as a slide canvas. Idempotent when the same src is already in that section.
    """
    if not embeds:
        return markdown
    by_number = {int(e.section_number): e for e in embeds}
    matches = list(_SECTION_HEADING_RE.finditer(markdown or ""))
    if not matches:
        raise ValueError(
            "no '## Slide-equivalent N' headings — cannot embed images at a section. "
            "Fix: export the speaking-script markdown first."
        )
    prefix = markdown[: matches[0].start()]
    pieces: list[str] = [prefix]
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        heading = match.group(1)
        number = int(match.group(2))
        body = markdown[match.end() : end]
        embed = by_number.get(number)
        if embed is not None:
            body = _insert_figure_in_section(body, embed)
        pieces.append(heading + body)
    return "".join(pieces)


def write_presenter_chart_png(
    path: Path,
    *,
    values: tuple[int, ...] = (12, 4, 8),
    labels: tuple[str, ...] = ("Staged", "Rejected", "Committed"),
) -> Path:
    """Write a small bar chart PNG (no extra dependency) for a presenter visual."""
    import struct
    import zlib

    width, height = 480, 240
    bg = (252, 250, 247)
    bar_colors = ((47, 93, 140), (166, 68, 72), (62, 128, 96))
    rows = bytearray()
    max_v = max(values) if values else 1
    left, right, top, bottom = 48, 24, 28, 36
    chart_w = width - left - right
    chart_h = height - top - bottom
    n = len(values)
    gap = 16
    bar_w = max(8, (chart_w - gap * (n + 1)) // max(n, 1))

    def pixel(x: int, y: int) -> tuple[int, int, int]:
        if x < 0 or y < 0 or x >= width or y >= height:
            return bg
        # baseline
        if top + chart_h - 1 <= y <= top + chart_h + 1 and left <= x <= width - right:
            return (40, 40, 40)
        for i, value in enumerate(values):
            x0 = left + gap + i * (bar_w + gap)
            x1 = x0 + bar_w
            bar_h = int(chart_h * (value / max_v))
            y0 = top + chart_h - bar_h
            if x0 <= x < x1 and y0 <= y < top + chart_h:
                return bar_colors[i % len(bar_colors)]
        return bg

    for y in range(height):
        rows.append(0)  # filter none
        for x in range(width):
            r, g, b = pixel(x, y)
            rows.extend((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )
    return path


def write_image_bearing_script(
    source_markdown: Path,
    dest_dir: Path,
    embeds: list[SectionImageEmbed],
    *,
    product_name: str = "ClarityDocs",
) -> dict[str, Path]:
    """Copy a speaking script, embed captioned images, guard the export."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    source = Path(source_markdown)
    markdown = embed_images_into_markdown(source.read_text(encoding="utf-8"), embeds)
    md_path = dest / source.name
    md_path.write_text(markdown, encoding="utf-8")
    title = _script_title(product_name)
    _guard_export_or_raise(md_path, title=title, export_format="markdown")
    return {"markdown": md_path}


async def _export_markdown_text(client: SuperDocsClient, session_id: str) -> str:
    export = await client.export(session_id=session_id, format="markdown")
    return (
        export.get("text")
        or export.get("markdown")
        or export.get("content")
        or ""
    )


async def _download_bytes(url: str) -> bytes:
    async with httpx2.AsyncClient(timeout=None) as http:
        response = await http.get(url)
        response.raise_for_status()
        return response.content


def _script_title(product_name: str) -> str:
    return f"{product_name} — Pitch Speaking Script"


def _guard_export_or_raise(
    path: Path,
    *,
    title: str,
    export_format: str,
) -> None:
    """Run format_guard; on failure remove the file so a bad export never lands."""
    try:
        assert_not_deck(path, title, export_format=export_format)
    except FormatGuardError as exc:
        if path.exists():
            path.unlink()
        raise FormatGuardError(f"export blocked — {exc}") from exc


async def export_narrative_files(
    client: SuperDocsClient,
    session_id: str,
    vertical_code: str,
    product_name: str = "ClarityDocs",
    out_dir: Path | None = None,
    image_embeds: list[SectionImageEmbed] | None = None,
) -> dict[str, Path]:
    """Export speaking script to markdown + docx under out/. Never a presentation path.

    No export completes without passing format_guard.assert_not_deck. A guard
    failure blocks the export and names which check failed.

    ``image_embeds`` re-homes generated figures into the named slide-equivalent
    with a presenter caption so SuperDocs placement drift cannot leave a visual
    floating outside its section.
    """
    dest = out_dir or OUT_DIR
    dest.mkdir(parents=True, exist_ok=True)
    slug = product_name.lower().replace(" ", "")
    base = f"pitch-script-{vertical_code}-{slug}"
    title = _script_title(product_name)

    md_export = await client.export(
        session_id=session_id,
        format="markdown",
        filename=base,
    )
    markdown = (
        md_export.get("text")
        or md_export.get("markdown")
        or md_export.get("content")
        or ""
    )
    if image_embeds:
        markdown = embed_images_into_markdown(markdown, image_embeds)
    md_path = dest / f"{base}.md"
    md_path.write_text(markdown, encoding="utf-8")
    _guard_export_or_raise(md_path, title=title, export_format="markdown")

    docx_export = await client.export(
        session_id=session_id,
        format="docx",
        filename=base,
    )
    download_url = docx_export.get("download_url")
    if not download_url:
        raise SuperDocsClientError(
            "docx export returned no download_url. Fix: binary exports are documented "
            "to return a signed download_url — check the response shape."
        )
    docx_path = dest / f"{base}.docx"
    docx_path.write_bytes(await _download_bytes(download_url))
    _guard_export_or_raise(docx_path, title=title, export_format="docx")
    return {"markdown": md_path, "docx": docx_path}


async def fill_narrative_sections(
    client: SuperDocsClient,
    session_id: str,
    product: dict[str, Any],
    vertical: dict[str, Any],
    manifest: dict[str, Any],
    pre_edit: dict[int, str],
    *,
    vertical_code: str,
    ledger: Ledger | None = None,
) -> dict[str, Any]:
    """Batched chat fill (config batch cap) with landed-check and split-retry."""
    sections = list(manifest.get("sections") or [])
    numbers = [int(s["number"]) for s in sections]
    by_number = {int(s["number"]): s for s in sections}
    batches = chunk_section_numbers(numbers, max_batch=chat_batch_cap())
    responses: list[dict] = []
    ceiling = parse_ops_ceiling()

    async def fetch_post(sid: str) -> dict[int, str]:
        md = await _export_markdown_text(client, sid)
        return parse_script_sections(md)

    for batch in batches:
        batch_sections = [by_number[n] for n in batch]
        instruction = build_batch_instruction(product, vertical, batch_sections)
        started = time.monotonic()
        result = await client.chat_with_landed_check(
            message=instruction,
            session_id=session_id,
            section_numbers=batch,
            pre_edit=pre_edit,
            fetch_post_edit=fetch_post,
            max_batch=len(batch),
            response_mode="compact",
        )
        elapsed = time.monotonic() - started
        batch_responses = result.get("responses") or []
        responses.extend(batch_responses)
        ops = sum(ops_from_response(r) if isinstance(r, dict) else 0 for r in batch_responses)
        if ops == 0 and batch_responses:
            # Compact apply path may omit usage; charge 1 per chat call in the batch.
            ops = len(batch_responses)
        if ledger is not None:
            ledger.record(
                step="chat",
                vertical=f"{vertical_code} sections {batch}",
                chat_calls=ops,
                wall_time=elapsed,
                content_key=f"narrative:{vertical_code}:batch:{batch}:v{manifest.get('manifest_version', 1)}",
                output_exists=False,
            )
            ledger.enforce_ceiling(ceiling)
        logger.info(
            "batch %s ready_to_approve=%s landed=%s failed=%s ops=%s",
            batch,
            result.get("ready_to_approve"),
            result.get("landed"),
            result.get("failed"),
            ops,
        )

    for response in responses:
        job_id = response.get("job_id") or (response.get("job") or {}).get("id")
        if not job_id:
            continue
        try:
            await client.approve(
                session_id=session_id,
                job_id=str(job_id),
                approved=True,
                changes=[{"approved": True}],
            )
        except SuperDocsClientError as exc:
            logger.warning("approve skipped/failed for job %s: %s", job_id, exc)

    post = await fetch_post(session_id)
    final = landed_check(pre_edit, post, numbers)
    return {
        "session_id": session_id,
        "responses": responses,
        "landed": final["landed"],
        "failed": final["failed"],
        "post_edit": post,
        "ready": len(final["failed"]) == 0,
    }


async def generate_narrative(
    vertical_code: str,
    *,
    client: SuperDocsClient | None = None,
    session_id: str | None = None,
    out_dir: Path | None = None,
    ledger: Ledger | None = None,
) -> dict[str, Any]:
    """Upload skeleton, fill from vertical knowledge, landed-check, export md+docx."""
    bundle = load_validated()
    manifest = bundle["manifest"]
    product = bundle["product"]
    verticals = bundle["verticals"]
    if vertical_code not in verticals:
        raise KeyError(
            f"unknown vertical {vertical_code!r}; known: {sorted(verticals)}"
        )
    vertical = verticals[vertical_code]
    product_block = product.get("product") or product
    product_name = _text(product_block.get("name") or "ClarityDocs")
    skeleton = build_skeleton_html(manifest, product)
    skeleton = skeleton.replace(
        "Vertical: (to be filled).",
        f"Vertical: {_text(vertical.get('display_name') or vertical_code)}.",
    )
    pre_edit = skeleton_pre_edit_bodies(manifest)
    sid = session_id or f"pitch-script-{vertical_code}-{uuid.uuid4().hex[:8]}"
    file_b64 = base64.b64encode(skeleton.encode("utf-8")).decode("ascii")
    if ledger is None:
        ledger = Ledger()

    owns_client = client is None
    if owns_client:
        client = SuperDocsClient()
        await client.connect()
    assert client is not None
    try:
        started = time.monotonic()
        await client.upload(
            filename=f"pitch-script-{vertical_code}-skeleton.html",
            file_base64=file_b64,
            session_id=sid,
            return_html=False,
        )
        ledger.record(
            step="upload",
            vertical=vertical_code,
            chat_calls=0,
            wall_time=time.monotonic() - started,
            content_key=f"narrative:{vertical_code}:upload:v{manifest.get('manifest_version', 1)}",
            output_exists=False,
        )

        fill = await fill_narrative_sections(
            client,
            sid,
            product,
            vertical,
            manifest,
            pre_edit,
            vertical_code=vertical_code,
            ledger=ledger,
        )
        started = time.monotonic()
        paths = await export_narrative_files(
            client,
            sid,
            vertical_code,
            product_name=product_name,
            out_dir=out_dir,
        )
        ledger.record(
            step="export",
            vertical=vertical_code,
            chat_calls=0,
            wall_time=time.monotonic() - started,
            content_key=f"narrative:{vertical_code}:export:v{manifest.get('manifest_version', 1)}",
            output_exists=False,
        )
        ledger.save()
        ledger.report()
        markdown = paths["markdown"].read_text(encoding="utf-8")
        return {
            "vertical": vertical_code,
            "session_id": sid,
            "markdown": markdown,
            "paths": {k: str(v) for k, v in paths.items()},
            "landed": fill["landed"],
            "failed": fill["failed"],
            "ready": fill["ready"],
            "responses": fill["responses"],
            "ops_total": ledger.total_operations,
        }
    finally:
        if owns_client:
            await client.close()
