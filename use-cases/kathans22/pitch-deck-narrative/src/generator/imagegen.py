"""Decide (then later generate) supporting images for image_eligible sections.

The card requires the system to decide from actual section content — never force
an image onto every eligible section, and never skip every section by policy.
Decisions are written to the narrative's sidecar metadata before any generation.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .ledger import Ledger, ops_from_response, parse_ops_ceiling
from .manifest import load_deck_manifest, project_root
from .narrative import parse_script_sections

logger = logging.getLogger(__name__)

# Caption SuperDocs is asked to place with a generated figure — also the land marker.
PRESENTER_VISUAL_MARKER = "Presenter visual (not a slide)"

# Phase 2 / Prompt 7 live docs (docs/image-generation-billing.md): image generation
# is not a separate SKU. It rides a document-edit `chat` operation.
IMAGE_GENERATION_BILLING = "chat_operation"
IMAGE_GENERATION_BILLING_CERTAIN = True
IMAGE_GENERATION_BILLING_NOTE = (
    "AI image generation is billed as a normal document-edit chat operation "
    "(typically 1 op; not a distinct image SKU). Upload, export, and a skipped "
    "unwarranted section are 0 ops. Source: docs/image-generation-billing.md "
    "checked 18 August 2026 against Plans & Usage, Attachments, and the "
    "agent-editing playbook."
)

# Generic / unfilled bodies are not visualizable — do not invent a figure for them.
_PLACEHOLDER_RE = re.compile(
    r"PLACEHOLDER_|\[Insert speaker script here\]|Insert speaker script",
    re.IGNORECASE,
)
_FILLER_PHRASES = (
    "operational excellence",
    "strategic roadmap for the upcoming quarter",
    "strategic focus for the upcoming quarter",
    "aligned on the project timeline",
    "high-impact growth initiatives",
    "scaling our core service offerings",
)

_DIGIT_RE = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?\b")
_SPELLED_COUNTS = {
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
}
_SPELLED_RE = re.compile(
    r"\b(" + "|".join(sorted(_SPELLED_COUNTS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_TIME_UNIT_RE = re.compile(
    r"\b(hours?|weeks?|months?|days?|minutes?)\b",
    re.IGNORECASE,
)
_PERCENT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*%|\bpercent(?:age)?\b", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$\s*\d|\b(?:usd|dollars?)\b", re.IGNORECASE)
_COMPARE_RE = re.compile(
    r"\b(?:vs\.?|versus|compared with|compared to|before|after|"
    r"not weeks|not months|rather than|instead of|down from|up from)\b",
    re.IGNORECASE,
)
_PROCESS_RE = re.compile(
    r"\b(?:findings?|rejected|committed|reconcile[ds]?|staged|pilot|"
    r"campuses|sites|locations|control matrix)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageDecision:
    """Per-section eligibility decision recorded before any image is generated."""

    section_number: int
    title: str
    image_eligible: bool
    warranted: bool
    reason: str


@dataclass
class NarrativeImagePlan:
    """Decisions for one vertical's eligible sections, persisted as narrative metadata."""

    vertical: str
    source_path: str
    manifest_version: int
    decided_at: str
    sections: list[ImageDecision]

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "vertical": self.vertical,
            "source_path": self.source_path,
            "manifest_version": self.manifest_version,
            "decided_at": self.decided_at,
            "note": (
                "Decisions recorded before image generation. "
                "warranted=false means no image will be requested."
            ),
            "sections": [asdict(s) for s in self.sections],
        }


def metadata_path_for(markdown_path: Path) -> Path:
    """pitch-script-legal-claritydocs.md → pitch-script-legal-claritydocs.meta.json"""
    path = Path(markdown_path)
    return path.with_name(path.stem + ".meta.json")


def image_eligible_sections(manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return manifest sections tagged image_eligible (Proof/Case Study, ROI/Business Case)."""
    data = manifest if manifest is not None else load_deck_manifest()
    return [
        section
        for section in (data.get("sections") or [])
        if bool(section.get("image_eligible"))
    ]


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def _is_unfilled(body: str) -> bool:
    text = _norm(body)
    if _PLACEHOLDER_RE.search(text):
        return True
    if len(text) < 40:
        return True
    lowered = text.lower()
    filler_hits = sum(1 for phrase in _FILLER_PHRASES if phrase in lowered)
    # Generic corporate filler with no vertical substance.
    if filler_hits >= 1 and not _DIGIT_RE.search(text) and not _PROCESS_RE.search(text):
        return True
    return False


def _quantities(body: str) -> list[str]:
    digits = _DIGIT_RE.findall(body or "")
    spelled = [m.group(0).lower() for m in _SPELLED_RE.finditer(body or "")]
    return digits + spelled


def decide_image_for_section(
    section: dict[str, Any],
    body: str,
) -> ImageDecision:
    """Decide from this section's actual content whether a supporting image is warranted.

    Examples the card cares about:
    - ROI that names numbers a chart would clarify → yes
    - Proof that names a single reference story with no comparative figures → no
    """
    number = int(section["number"])
    title = str(section.get("title") or "")
    eligible = bool(section.get("image_eligible"))
    if not eligible:
        return ImageDecision(
            section_number=number,
            title=title,
            image_eligible=False,
            warranted=False,
            reason="section is not image_eligible in the deck manifest",
        )

    text = body or ""
    title_l = title.lower()
    is_roi = "roi" in title_l or "business case" in title_l
    is_proof = "proof" in title_l or "case study" in title_l

    if _is_unfilled(text):
        return ImageDecision(
            section_number=number,
            title=title,
            image_eligible=True,
            warranted=False,
            reason="section body is placeholder or generic filler, not visualizable substance",
        )

    quantities = _quantities(text)
    has_compare = bool(_COMPARE_RE.search(text))
    has_time = bool(_TIME_UNIT_RE.search(text))
    has_percent = bool(_PERCENT_RE.search(text))
    has_money = bool(_MONEY_RE.search(text))
    has_process = bool(_PROCESS_RE.search(text))
    distinct_qty = {q.lower() if isinstance(q, str) else q for q in quantities}

    if is_roi:
        chartable = (
            (len(distinct_qty) >= 1 and (has_compare or has_time or has_percent or has_money))
            or (has_percent or has_money)
            or (len(distinct_qty) >= 2 and has_process)
        )
        if chartable:
            return ImageDecision(
                section_number=number,
                title=title,
                image_eligible=True,
                warranted=True,
                reason="ROI names quantities or time/cost comparisons a chart would clarify",
            )
        return ImageDecision(
            section_number=number,
            title=title,
            image_eligible=True,
            warranted=False,
            reason="ROI is qualitative; no figures a chart would clarify",
        )

    if is_proof:
        # A staged case with multiple counts (e.g. 12 findings / 4 rejected / 8 committed)
        # or a before/after with numbers is worth a figure. A single named story is not.
        multi_count = len(distinct_qty) >= 3 and has_process
        before_after = has_compare and len(distinct_qty) >= 1
        if multi_count or before_after:
            return ImageDecision(
                section_number=number,
                title=title,
                image_eligible=True,
                warranted=True,
                reason="proof names comparative counts a figure would make scanable",
            )
        return ImageDecision(
            section_number=number,
            title=title,
            image_eligible=True,
            warranted=False,
            reason="single reference story without comparative figures; a visual would not add",
        )

    # Other eligible titles (none today): require chartable quantities.
    if len(distinct_qty) >= 2 and (has_compare or has_time):
        return ImageDecision(
            section_number=number,
            title=title,
            image_eligible=True,
            warranted=True,
            reason="section names comparative quantities a supporting visual would clarify",
        )
    return ImageDecision(
        section_number=number,
        title=title,
        image_eligible=True,
        warranted=False,
        reason="eligible but content does not call for a supporting image",
    )


def decide_images_for_narrative(
    markdown: str,
    *,
    vertical: str,
    source_path: str | Path = "",
    manifest: dict[str, Any] | None = None,
) -> NarrativeImagePlan:
    """Decide for every image_eligible section in one exported speaking script."""
    data = manifest if manifest is not None else load_deck_manifest()
    bodies = parse_script_sections(markdown)
    decided_at = datetime.now(timezone.utc).isoformat()
    sections = [
        decide_image_for_section(section, bodies.get(int(section["number"]), ""))
        for section in image_eligible_sections(data)
    ]
    return NarrativeImagePlan(
        vertical=vertical,
        source_path=str(source_path),
        manifest_version=int(data.get("manifest_version") or 1),
        decided_at=decided_at,
        sections=sections,
    )


def write_narrative_metadata(markdown_path: Path, plan: NarrativeImagePlan) -> Path:
    """Persist decisions next to the narrative *before* any image is generated."""
    dest = metadata_path_for(Path(markdown_path))
    dest.write_text(json.dumps(plan.to_json_dict(), indent=2) + "\n", encoding="utf-8")
    return dest


def load_narrative_metadata(markdown_path: Path) -> dict[str, Any]:
    dest = metadata_path_for(Path(markdown_path))
    return json.loads(dest.read_text(encoding="utf-8"))


def decide_and_record(
    markdown_path: Path,
    *,
    vertical: str | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[NarrativeImagePlan, Path]:
    """Load a script, decide, write sidecar metadata. Does not generate images."""
    path = Path(markdown_path)
    text = path.read_text(encoding="utf-8")
    code = vertical
    if code is None:
        parts = path.stem.split("-")
        # pitch-script-<vertical>-<product>
        code = parts[2] if len(parts) >= 4 else path.stem
    plan = decide_images_for_narrative(
        text,
        vertical=code,
        source_path=path,
        manifest=manifest,
    )
    meta_path = write_narrative_metadata(path, plan)
    return plan, meta_path


def default_narratives_dir() -> Path:
    evidence = project_root() / "evidence" / "narratives"
    if evidence.is_dir() and any(evidence.glob("pitch-script-*-*.md")):
        return evidence
    return project_root() / "out"


def decide_all_verticals(
    narratives_dir: Path | None = None,
    *,
    manifest: dict[str, Any] | None = None,
) -> list[tuple[NarrativeImagePlan, Path]]:
    """Run the decision pass on every pitch-script-*.md found (typically four verticals)."""
    dest = Path(narratives_dir) if narratives_dir is not None else default_narratives_dir()
    results: list[tuple[NarrativeImagePlan, Path]] = []
    for path in sorted(dest.glob("pitch-script-*-*.md")):
        parts = path.stem.split("-")
        if len(parts) < 4 or parts[0] != "pitch" or parts[1] != "script":
            continue
        results.append(decide_and_record(path, vertical=parts[2], manifest=manifest))
    return results


def _ops_for_image_response(response: dict | list[dict] | None) -> tuple[int, str]:
    """Return (ops, how we knew). Billing is a chat op — confirmed, not guessed."""
    if response is None:
        return 0, "no_response"
    payloads = response if isinstance(response, list) else [response]
    total = 0
    saw_usage = False
    for item in payloads:
        if not isinstance(item, dict):
            continue
        usage = item.get("usage")
        if usage is not None:
            saw_usage = True
        total += ops_from_response(item) if isinstance(item, dict) else 0
    if saw_usage:
        return total, "usage.was_billable"
    # Compact chat can omit usage the same way narrative fill does; one generate
    # chat that applied a change is one op per Phase 2 billing note.
    return max(total, 1 if payloads else 0), "chat_op_fallback_usage_omitted"


def charge_image_operations(
    ledger: Ledger,
    results: list[dict[str, Any]],
    *,
    manifest_version: int = 1,
) -> list[dict[str, Any]]:
    """Charge the ledger for generated images; skip-charge unwarranted sections.

    Billing certainty: IMAGE_GENERATION_BILLING_CERTAIN is True — this is a chat
    operation, not an unknown surcharge.
    """
    ceiling = parse_ops_ceiling()
    charged: list[dict[str, Any]] = []
    for row in results:
        vertical = str(row.get("vertical") or "")
        number = int(row["section_number"])
        key = f"image:{vertical}:section:{number}:v{manifest_version}"
        if row.get("skipped") or not row.get("generated"):
            entry = ledger.record(
                step="image",
                vertical=f"{vertical} section {number} skipped",
                chat_calls=0,
                wall_time=0.0,
                content_key=key,
                output_exists=False,
            )
            # Force skip semantics: unwarranted means we never called SuperDocs.
            entry.status = "SKIPPED"
            entry.operations = 0
            updated = {
                **row,
                "ops_charged": 0,
                "billing": IMAGE_GENERATION_BILLING,
                "billing_certain": IMAGE_GENERATION_BILLING_CERTAIN,
                "billing_note": IMAGE_GENERATION_BILLING_NOTE,
                "ledger_status": "SKIPPED",
            }
            charged.append(updated)
            continue
        ops, how = _ops_for_image_response(row.get("response"))
        entry = ledger.record(
            step="image",
            vertical=f"{vertical} section {number}",
            chat_calls=ops,
            wall_time=float(row.get("wall_time") or 0.0),
            content_key=key,
            output_exists=False,
        )
        ledger.enforce_ceiling(ceiling)
        charged.append(
            {
                **row,
                "ops_charged": entry.operations,
                "ops_source": how,
                "billing": IMAGE_GENERATION_BILLING,
                "billing_certain": IMAGE_GENERATION_BILLING_CERTAIN,
                "billing_note": IMAGE_GENERATION_BILLING_NOTE,
                "ledger_status": entry.status,
            }
        )
    return charged


class ImageChatClient(Protocol):
    """Minimal chat surface used for image insertion (real SuperDocsClient or a test double)."""

    async def chat(
        self,
        message: str,
        session_id: str,
        **kwargs: Any,
    ) -> dict | list[dict]: ...


def section_has_supporting_visual(body: str) -> bool:
    """True if the section already contains an inserted supporting image/caption."""
    text = (body or "").lower()
    return (
        PRESENTER_VISUAL_MARKER.lower() in text
        or "<img" in text
        or "![" in (body or "")
    )


def build_image_instruction(decision: ImageDecision) -> str:
    """Chat instruction: generate one figure in this section only, never a slide layout."""
    n = decision.section_number
    title = decision.title
    return f"""
This document is a SPEAKING SCRIPT — not a slide deck. Do not create a slide
layout, slide canvas, or anything confusable with a presentation file.

In slide-equivalent {n} — {title} ONLY:
- Generate one supporting image that clarifies this reason: {decision.reason}
- Insert the image in that section, after the talking point and before the
  speaker notes (or at the end of the section if those labels are missing).
- Directly under the image, add a one-line caption starting with:
  {PRESENTER_VISUAL_MARKER}:
  followed by a short description of what the presenter should point at.
- Do not change the talking point or speaker notes wording.
- Do not add images to any other section.
- Do not add bullet-slide layouts, large title cards, or deck chrome.

Decision already recorded in metadata: warranted=yes for this section.
""".strip()


def plan_from_metadata(payload: dict[str, Any]) -> NarrativeImagePlan:
    """Rebuild a plan from sidecar JSON — generation must follow recorded decisions."""
    sections = [
        ImageDecision(
            section_number=int(row["section_number"]),
            title=str(row["title"]),
            image_eligible=bool(row["image_eligible"]),
            warranted=bool(row["warranted"]),
            reason=str(row["reason"]),
        )
        for row in payload.get("sections") or []
    ]
    return NarrativeImagePlan(
        vertical=str(payload.get("vertical") or ""),
        source_path=str(payload.get("source_path") or ""),
        manifest_version=int(payload.get("manifest_version") or 1),
        decided_at=str(payload.get("decided_at") or ""),
        sections=sections,
    )


async def generate_images_from_plan(
    client: ImageChatClient,
    session_id: str,
    plan: NarrativeImagePlan,
    *,
    metadata_path: Path | None = None,
    ledger: Ledger | None = None,
) -> list[dict[str, Any]]:
    """Generate a supporting image only where the recorded decision is warranted=yes.

    Refuses to run if metadata was not written first (the card: decide, record, then generate).
    Sections with warranted=false are skipped — no chat call.
    """
    if metadata_path is not None and not Path(metadata_path).is_file():
        raise FileNotFoundError(
            f"narrative metadata missing at {metadata_path}. "
            "Fix: call decide_and_record before generating any image."
        )
    results: list[dict[str, Any]] = []
    for decision in plan.sections:
        if not decision.warranted:
            logger.info(
                "skip image for %s section %s: %s",
                plan.vertical,
                decision.section_number,
                decision.reason,
            )
            results.append(
                {
                    "vertical": plan.vertical,
                    "section_number": decision.section_number,
                    "title": decision.title,
                    "warranted": False,
                    "generated": False,
                    "skipped": True,
                    "reason": decision.reason,
                    "response": None,
                    "wall_time": 0.0,
                }
            )
            continue
        message = build_image_instruction(decision)
        started = time.monotonic()
        response = await client.chat(
            message,
            session_id,
            section_numbers=[decision.section_number],
            max_batch=1,
            response_mode="compact",
        )
        elapsed = time.monotonic() - started
        results.append(
            {
                "vertical": plan.vertical,
                "section_number": decision.section_number,
                "title": decision.title,
                "warranted": True,
                "generated": True,
                "skipped": False,
                "reason": decision.reason,
                "response": response,
                "wall_time": elapsed,
            }
        )
    if ledger is not None:
        return charge_image_operations(
            ledger,
            results,
            manifest_version=plan.manifest_version,
        )
    return results


async def generate_images_for_markdown(
    markdown_path: Path,
    *,
    vertical: str | None = None,
    client: Any | None = None,
    session_id: str | None = None,
    out_dir: Path | None = None,
    ledger: Ledger | None = None,
) -> dict[str, Any]:
    """Decide+record metadata, upload the script, generate only where warranted=yes.

    Export is 0 ops. Operation charging is a separate step.
    """
    from .mcp_client import SuperDocsClient

    path = Path(markdown_path)
    plan, meta_path = decide_and_record(path, vertical=vertical)
    sid = session_id or f"pitch-images-{plan.vertical}-{uuid.uuid4().hex[:8]}"
    owns_client = client is None
    if owns_client:
        client = SuperDocsClient()
        await client.connect()
    assert client is not None
    try:
        raw = path.read_bytes()
        await client.upload(
            filename=path.name,
            file_base64=base64.b64encode(raw).decode("ascii"),
            session_id=sid,
            return_html=False,
        )
        results = await generate_images_from_plan(
            client,
            sid,
            plan,
            metadata_path=meta_path,
            ledger=ledger,
        )
        dest = out_dir or path.parent
        from .narrative import (
            _guard_export_or_raise,
            _script_title,
            embed_images_into_markdown,
            embeds_from_generated_results,
            export_narrative_files,
        )

        paths = await export_narrative_files(
            client,
            sid,
            plan.vertical,
            out_dir=dest,
        )
        markdown = paths["markdown"].read_text(encoding="utf-8")
        embeds = embeds_from_generated_results(results, markdown)
        if embeds:
            markdown = embed_images_into_markdown(markdown, embeds)
            paths["markdown"].write_text(markdown, encoding="utf-8")
            _guard_export_or_raise(
                paths["markdown"],
                title=_script_title("ClarityDocs"),
                export_format="markdown",
            )
        # Keep metadata beside the (possibly overwritten) export.
        write_narrative_metadata(paths["markdown"], plan)
        return {
            "vertical": plan.vertical,
            "session_id": sid,
            "metadata_path": str(meta_path),
            "plan": plan.to_json_dict(),
            "image_results": results,
            "paths": {k: str(v) for k, v in paths.items()},
        }
    finally:
        if owns_client:
            await client.close()
