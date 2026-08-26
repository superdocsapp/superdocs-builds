"""Image eligibility decisions — no SuperDocs, no network."""

from __future__ import annotations

import json
from pathlib import Path

from generator.imagegen import (
    decide_and_record,
    decide_image_for_section,
    image_eligible_sections,
)
from generator.manifest import load_deck_manifest


def _section(number: int, title: str, *, eligible: bool = True) -> dict:
    return {"number": number, "title": title, "weight": "vertical", "image_eligible": eligible}


PROOF = _section(6, "Proof / Case Study")
ROI = _section(8, "ROI / Business Case")


def test_manifest_marks_only_proof_and_roi_eligible() -> None:
    eligible = image_eligible_sections(load_deck_manifest())
    numbers = [int(s["number"]) for s in eligible]
    titles = [s["title"] for s in eligible]
    assert numbers == [6, 8]
    assert titles == ["Proof / Case Study", "ROI / Business Case"]


def test_roi_with_numbers_is_warranted() -> None:
    body = (
        "Talking point: Cut review from 14 days to 3 hours per pack. "
        "Speaker notes: The Cedar Ward pilot moved from months of drift to a "
        "staged review that rejected two over-strong claims and kept the rest."
    )
    decision = decide_image_for_section(ROI, body)
    assert decision.image_eligible is True
    assert decision.warranted is True
    assert "chart" in decision.reason.lower() or "quantit" in decision.reason.lower()


def test_proof_single_story_without_figures_is_not_warranted() -> None:
    body = (
        "Talking point: Northbridge's KM lead saw the clause-drift register land. "
        "Speaker notes: One named engagement team exported a clean DOCX brief. "
        "That single reference story is the proof — no before/after counts, no "
        "staged findings tally, just the moment partners trusted the pack."
    )
    decision = decide_image_for_section(PROOF, body)
    assert decision.warranted is False
    assert "story" in decision.reason.lower()


def test_proof_with_staged_counts_is_warranted() -> None:
    body = (
        "Talking point: HarborPay reconciled three policy versions in hours, not weeks. "
        "Speaker notes: The team staged twelve findings, rejected four as over-claims, "
        "and committed eight with PDF citations against the control matrix."
    )
    decision = decide_image_for_section(PROOF, body)
    assert decision.warranted is True


def test_placeholder_body_is_not_warranted() -> None:
    body = "*Talking point:* [Insert speaker script here]\n*Speaker notes:* PLACEHOLDER_SPEAKER_NOTES_6"
    decision = decide_image_for_section(PROOF, body)
    assert decision.warranted is False
    assert "placeholder" in decision.reason.lower() or "filler" in decision.reason.lower()


def test_non_eligible_section_is_never_warranted() -> None:
    opening = _section(1, "Opening / Hook", eligible=False)
    decision = decide_image_for_section(opening, "We saved 40% and 12 days versus 3 weeks.")
    assert decision.warranted is False
    assert decision.image_eligible is False


def test_metadata_written_before_generation_contains_reasons(tmp_path: Path) -> None:
    markdown = "\n".join(
        [
            "# ClarityDocs — Pitch Speaking Script",
            "",
            "**Speaking script — not a slide deck.**",
            "",
            "## Slide-equivalent 6 — Proof / Case Study",
            "",
            "Northbridge ran one reference engagement and exported a DOCX brief.",
            "",
            "## Slide-equivalent 8 — ROI / Business Case",
            "",
            "Review time fell from 14 days to 3 hours; that is the chartable case.",
            "",
        ]
    )
    script = tmp_path / "pitch-script-legal-claritydocs.md"
    script.write_text(markdown, encoding="utf-8")
    plan, meta_path = decide_and_record(script, vertical="legal")
    assert meta_path.is_file()
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    assert payload["vertical"] == "legal"
    by_n = {row["section_number"]: row for row in payload["sections"]}
    assert by_n[6]["warranted"] is False
    assert by_n[8]["warranted"] is True
    assert plan.sections[0].reason
    assert "before image generation" in payload["note"].lower()


def test_generate_only_where_decision_is_yes() -> None:
    """Chat is issued only for warranted sections; skipped sections never call the client."""
    import asyncio

    from generator.imagegen import (
        ImageDecision,
        NarrativeImagePlan,
        generate_images_from_plan,
    )

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def chat(self, message: str, session_id: str, **kwargs):
            nums = kwargs.get("section_numbers") or []
            self.calls.extend(int(n) for n in nums)
            return {"ok": True, "message": message}

    plan = NarrativeImagePlan(
        vertical="fintech",
        source_path="unused.md",
        manifest_version=1,
        decided_at="2026-08-18T00:00:00+00:00",
        sections=[
            ImageDecision(6, "Proof / Case Study", True, True, "comparative counts"),
            ImageDecision(8, "ROI / Business Case", True, False, "qualitative only"),
        ],
    )
    client = FakeClient()
    results = asyncio.run(generate_images_from_plan(client, "sess-1", plan, metadata_path=None))
    assert client.calls == [6]
    by_n = {row["section_number"]: row for row in results}
    assert by_n[6]["generated"] is True and by_n[6]["skipped"] is False
    assert by_n[8]["generated"] is False and by_n[8]["skipped"] is True


def test_generate_refuses_without_metadata_file(tmp_path: Path) -> None:
    import asyncio

    from generator.imagegen import (
        ImageDecision,
        NarrativeImagePlan,
        generate_images_from_plan,
    )

    plan = NarrativeImagePlan(
        vertical="legal",
        source_path="x.md",
        manifest_version=1,
        decided_at="t",
        sections=[ImageDecision(6, "Proof / Case Study", True, True, "yes")],
    )

    class FakeClient:
        async def chat(self, message: str, session_id: str, **kwargs):
            raise AssertionError("must not chat when metadata is missing")

    missing = tmp_path / "pitch-script-legal-claritydocs.meta.json"
    try:
        asyncio.run(
            generate_images_from_plan(FakeClient(), "s", plan, metadata_path=missing)
        )
        raise AssertionError("expected FileNotFoundError")
    except FileNotFoundError as exc:
        assert "metadata missing" in str(exc)


def test_image_ops_charged_only_when_generated() -> None:
    import asyncio

    from generator.imagegen import (
        IMAGE_GENERATION_BILLING,
        IMAGE_GENERATION_BILLING_CERTAIN,
        ImageDecision,
        NarrativeImagePlan,
        generate_images_from_plan,
    )
    from generator.ledger import Ledger

    class FakeClient:
        async def chat(self, message: str, session_id: str, **kwargs):
            return {"usage": {"was_billable": True, "ops_charged": 1}}

    plan = NarrativeImagePlan(
        vertical="healthcare",
        source_path="h.md",
        manifest_version=1,
        decided_at="t",
        sections=[
            ImageDecision(6, "Proof / Case Study", True, False, "filler"),
            ImageDecision(8, "ROI / Business Case", True, True, "chartable"),
        ],
    )
    ledger = Ledger()
    results = asyncio.run(
        generate_images_from_plan(FakeClient(), "s", plan, ledger=ledger)
    )
    assert IMAGE_GENERATION_BILLING == "chat_operation"
    assert IMAGE_GENERATION_BILLING_CERTAIN is True
    by_n = {row["section_number"]: row for row in results}
    assert by_n[6]["ops_charged"] == 0 and by_n[6]["ledger_status"] == "SKIPPED"
    assert by_n[8]["ops_charged"] == 1 and by_n[8]["billing_certain"] is True
    assert ledger.total_operations == 1
