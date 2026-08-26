"""Live probe: does a 4-section chat batch still silently no-op?

Requires SUPERDOCS_API_KEY. Skips cleanly when unset so offline CI stays green.
"""

from __future__ import annotations

import asyncio
import base64
import os
import re
from pathlib import Path

import pytest

from generator.mcp_client import SuperDocsClient, landed_check, normalise_section_text

PROJECT = Path(__file__).resolve().parents[1]


def _load_api_key() -> str | None:
    """Prefer the process env, then this project's local ``.env`` (never a machine path)."""
    key = os.environ.get("SUPERDOCS_API_KEY")
    if key and key.strip() and key.strip() != "your-key-here":
        return key.strip()
    env_path = PROJECT / ".env"
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("SUPERDOCS_API_KEY="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value and value != "your-key-here":
                    os.environ["SUPERDOCS_API_KEY"] = value
                    return value
    return None


def _scaffold_html() -> str:
    parts = [
        "<html><body>",
        "<p>Speaking script — not a slide deck.</p>",
    ]
    for n in (1, 2, 3, 4):
        parts.append(f"<h2>Slide-equivalent {n} — Placeholder {n}</h2>")
        parts.append(f"<p>PLACEHOLDER_BODY_{n}_UNEDITED</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def _parse_section_bodies(markdown: str) -> dict[int, str]:
    """Very small heading parser for the live probe scaffold."""
    bodies: dict[int, str] = {}
    pattern = re.compile(
        r"^##\s+Slide-equivalent\s+(\d+)[^\n]*\n(.*?)(?=^##\s+Slide-equivalent|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(markdown):
        bodies[int(match.group(1))] = match.group(2).strip()
    # Fallback: look for placeholder tokens if heading parse fails.
    if len(bodies) < 4:
        for n in (1, 2, 3, 4):
            token = f"PLACEHOLDER_BODY_{n}_UNEDITED"
            if token in markdown:
                bodies[n] = token
            elif n not in bodies:
                bodies[n] = ""
    return bodies


@pytest.mark.asyncio
async def test_four_section_batch_behavior_live() -> None:
    key = _load_api_key()
    if not key:
        pytest.skip("SUPERDOCS_API_KEY not available — live batch probe skipped")

    html = _scaffold_html()
    file_b64 = base64.b64encode(html.encode("utf-8")).decode("ascii")
    session_id = "pitch-deck-narrative-batch-probe"

    pre_edit = {
        1: "PLACEHOLDER_BODY_1_UNEDITED",
        2: "PLACEHOLDER_BODY_2_UNEDITED",
        3: "PLACEHOLDER_BODY_3_UNEDITED",
        4: "PLACEHOLDER_BODY_4_UNEDITED",
    }

    async with SuperDocsClient() as client:
        await client.upload(
            filename="batch-probe.html",
            file_base64=file_b64,
            session_id=session_id,
            return_html=False,
        )

        # Force a single 4-section call — do NOT use the cap-2 auto-split.
        instruction = (
            "Rewrite ONLY slide-equivalent sections 1, 2, 3 and 4. "
            "For each section replace the placeholder body with unique text that "
            "clearly includes the marker LANDED_SECTION_<number>. "
            "Do not leave PLACEHOLDER_BODY_* text. "
            "Keep headings. This is a speaking script, not a slide deck."
        )
        response = await client._chat_once(
            instruction,
            session_id,
            response_mode="compact",
        )

        export = await client.export(session_id=session_id, format="markdown")
        markdown = (
            export.get("text")
            or export.get("markdown")
            or export.get("content")
            or ""
        )
        post_edit = _parse_section_bodies(markdown)
        check = landed_check(pre_edit, post_edit, [1, 2, 3, 4])

    evidence_dir = PROJECT / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    report_path = evidence_dir / "batch-4-section-probe.md"
    reply_text = ""
    if isinstance(response, dict):
        reply_text = str(
            response.get("message")
            or response.get("text")
            or response.get("reply")
            or ""
        )[:2000]

    silent_noop = len(check["landed"]) == 0
    report = "\n".join(
        [
            "# Live probe — 4-section chat batch",
            "",
            f"**Date:** 18 August 2026",
            f"**Session:** `{session_id}`",
            f"**Landed:** {check['landed']}",
            f"**Failed (unchanged):** {check['failed']}",
            f"**Silent no-op?** {'YES — none of 4 sections changed' if silent_noop else 'NO — at least one section changed'}",
            "",
            "## Implication",
            (
                "Build 1's finding still holds: a 4-section batch can fail to land. "
                "Keep SUPERDOCS_CHAT_BATCH_CAP=2 and landed-check + split-retry."
                if silent_noop
                else (
                    "API behaviour may have improved since Build 1 (at least one section "
                    f"landed: {check['landed']}). Cap=2 remains the safe default until "
                    "repeated probes show 4-section batches are reliable; do not remove "
                    "landed-check."
                )
            ),
            "",
            "## Post-edit section fingerprints (normalised, truncated)",
            *[
                f"- section {n}: `{normalise_section_text(post_edit.get(n, ''))[:120]}`"
                for n in (1, 2, 3, 4)
            ],
            "",
            "## Chat reply excerpt (may claim success even on no-op)",
            "```",
            reply_text or "(empty / compact)",
            "```",
            "",
        ]
    )
    report_path.write_text(report, encoding="utf-8")

    # Soft assertion: we always record evidence. Hard-fail only if the probe
    # itself could not run (empty export). Behaviour change is reported, not assumed.
    assert markdown, "export returned empty markdown — probe inconclusive"
    # Expose outcome for humans reading pytest output.
    print(report)
    assert check["landed"] or check["failed"]
