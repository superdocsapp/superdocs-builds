"""A real-model check on Task 2.2's schedule-fact extraction quality, not
just plumbing. The fake-client tests (test_close_package_schedule.py,
test_llm_client.py) prove our code handles whatever the model returns
correctly -- they cannot prove the model actually finds real, correctly-
cited recognition-period facts from a real contract, or that it produces
the same kind of quirks that were found in Task 2's own real-model
testing (concatenated citations, an obligation_id leaking into a quote,
etc.). Same VCR pattern as tests/test_drafter_analysis_real_model.py:
record once against a real model, replay after.

Uses the hardware+warranty fixture specifically because it has BOTH a
point-in-time obligation (equipment, single acceptance event) and a
genuinely multi-month over-time obligation (the 36-month extended
warranty) with an explicit term length stated in the contract's own
text -- the strongest real-model test of whether the model can tell the
two apart and extract the warranty's actual term length rather than
just restating vague language.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from close_package.schedule import (
    build_obligations_context,
    compute_schedule_entries,
    extract_schedule_facts,
)
from close_package.state import ClosePackageState
from core.citations import quote_is_verifiable
from core.llm import LLMClient
from drafter.state import DrafterState, MemoAnalysis

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "drafter"
CASSETTE_DIR = Path(__file__).parent / "fixtures" / "cassettes"

_cassette_exists = (
    CASSETTE_DIR / "test_real_model_extracts_hardware_warranty_schedule_facts.yaml"
).exists()
_recording_requested = os.environ.get("RECORD_LLM_CASSETTES") == "1"

pytestmark = pytest.mark.skipif(
    not (_cassette_exists or _recording_requested),
    reason=(
        "No recorded cassette, and RECORD_LLM_CASSETTES=1 was not set. Run "
        "with a real ANTHROPIC_API_KEY and that flag to record once."
    ),
)

# Task 2's own already-established, already-verified analysis for this
# fixture (copied from tests/test_drafter_integration.py's fake client --
# this is what a real draft_memo() run on this fixture actually produces).
_HARDWARE_ANALYSIS: MemoAnalysis = {
    "contract_filename": "contract_hardware_warranty.txt",
    "performance_obligations": [
        {
            "obligation_id": "equipment",
            "description": "Six Model PR-4400 automated packaging units",
            "source_quote": "manufacture, deliver, and install six (6) Model PR-4400 automated packaging units",
            "citation_verified": True,
            "is_distinct": True,
            "is_judgement": False,
            "judgement_note": "",
            "requires_human_review": False,
        },
        {
            "obligation_id": "extended_warranty",
            "description": "Three-year extended warranty",
            "source_quote": (
                "provide a three (3) year Extended Warranty covering parts, "
                "labor, and quarterly preventive maintenance visits"
            ),
            "citation_verified": True,
            "is_distinct": True,
            "is_judgement": True,
            "judgement_note": (
                "Because the Extended Warranty is separately priced and "
                "provides services distinct from and in addition to the "
                "Equipment, it constitutes a distinct performance "
                "obligation from the Equipment sale, per the contract's "
                "own reasoning."
            ),
            "requires_human_review": False,
        },
    ],
    "price_allocations": [
        {
            "obligation_id": "equipment",
            "allocated_amount": "$540,000",
            "allocation_basis": "stated explicitly in contract",
            "source_quote": (
                "The purchase price for the six (6) Equipment units, "
                "inclusive of delivery and installation, is $540,000"
            ),
            "citation_verified": True,
            "is_judgement": False,
            "judgement_note": "",
            "requires_human_review": False,
        },
        {
            "obligation_id": "extended_warranty",
            "allocated_amount": "$81,000",
            "allocation_basis": "stated explicitly in contract",
            "source_quote": "The price for the three (3) year Extended Warranty is $81,000",
            "citation_verified": True,
            "is_judgement": False,
            "judgement_note": "",
            "requires_human_review": False,
        },
    ],
    "timing_conclusions": [
        {
            "obligation_id": "equipment",
            "recognition_pattern": "point_in_time",
            "timing_basis": "control transfers upon written acceptance following installation",
            "source_quote": (
                "Title and control of the Equipment transfer to Buyer upon "
                "Buyer's written acceptance following successful "
                "installation and calibration testing"
            ),
            "citation_verified": True,
            "is_judgement": False,
            "judgement_note": "",
            "requires_human_review": False,
        },
        {
            "obligation_id": "extended_warranty",
            "recognition_pattern": "over_time",
            "timing_basis": "customer benefits from coverage throughout the warranty period",
            "source_quote": "continuing for thirty-six (36) months thereafter",
            "citation_verified": True,
            "is_judgement": False,
            "judgement_note": "",
            "requires_human_review": False,
        },
    ],
}


def _state(contract_text: str) -> ClosePackageState:
    memo_state: DrafterState = {
        "run_id": "real-model-test",
        "contract_path": "contract_hardware_warranty.txt",
        "contract_text": contract_text,
        "contract_filename": "contract_hardware_warranty.txt",
        "analysis": _HARDWARE_ANALYSIS,
        "judgement_notes": [],
        "memo_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }
    return {
        "run_id": "real-model-test",
        "memo_state": memo_state,
        "schedule": {
            "contract_filename": "contract_hardware_warranty.txt",
            "schedule_facts": [],
            "entries": [],
        },
        "audit_trail": [],
        "package_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }


@pytest.mark.vcr()
def test_real_model_extracts_hardware_warranty_schedule_facts() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-replay")
    llm = LLMClient(api_key=api_key)

    contract_text = (FIXTURES_DIR / "contract_hardware_warranty.txt").read_text()
    obligations_context = build_obligations_context(_HARDWARE_ANALYSIS)

    raw_facts = llm.extract_recognition_schedule_facts(contract_text, obligations_context)
    assert raw_facts, "model returned no schedule facts at all"

    # Every obligation_id the model used must be one Task 2 actually
    # established -- the real-model version of the same guarantee
    # extract_schedule_facts() enforces in code (never trust an invented id).
    known_ids = {"equipment", "extended_warranty"}
    used_ids = {f.get("obligation_id") for f in raw_facts}
    assert used_ids <= known_ids, f"model invented an obligation_id not in the context: {used_ids - known_ids}"

    # The warranty's term length must genuinely be extracted as 36 months --
    # not vaguely restated, not silently dropped.
    warranty_facts = [f for f in raw_facts if f.get("obligation_id") == "extended_warranty"]
    assert warranty_facts, f"model did not extract a schedule fact for the warranty at all: {raw_facts}"
    assert any(f.get("term_length_months") == 36 for f in warranty_facts), (
        f"model did not correctly extract the warranty's 36-month term: {warranty_facts}"
    )

    # Every citation across all returned facts must be genuinely verifiable
    # against the real contract text -- the real-model version of the same
    # guarantee close_package/schedule.py enforces in code.
    unverifiable = [
        f for f in raw_facts if not quote_is_verifiable(f.get("source_quote", ""), contract_text)
    ]
    assert not unverifiable, f"model produced unverifiable citations: {unverifiable}"

    # Run the actual extract_schedule_facts()/compute_schedule_entries()
    # pipeline on the real model output, not just the raw tool-call result --
    # proves our verification code and the model's real output actually fit
    # together, end to end, not just in isolation.
    state = _state(contract_text)
    state.update(extract_schedule_facts(state, llm))  # type: ignore[typeddict-item]
    state.update(compute_schedule_entries(state))  # type: ignore[typeddict-item]

    facts = state["schedule"]["schedule_facts"]
    warranty_verified = [
        f for f in facts if f["obligation_id"] == "extended_warranty" and f["citation_verified"]
    ]
    assert warranty_verified, f"no verified schedule fact survived for the warranty: {facts}"

    warranty_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "extended_warranty"]
    assert len(warranty_entries) == 36, f"expected 36 monthly entries for the warranty, got {len(warranty_entries)}"
    total = sum(float(e["recognized_amount"].replace("$", "").replace(",", "")) for e in warranty_entries)
    assert round(total, 2) == 81000.00, f"36 monthly entries did not reconstruct the $81,000 allocation: {total}"

    # The point-in-time equipment obligation should still be a single entry
    # -- confirms the real model's output doesn't accidentally get treated
    # as over-time for an obligation that isn't.
    equipment_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "equipment"]
    assert len(equipment_entries) == 1
    assert equipment_entries[0]["recognized_amount"] == "$540,000.00"
