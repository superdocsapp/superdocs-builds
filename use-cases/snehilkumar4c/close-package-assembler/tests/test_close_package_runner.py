"""End-to-end proof of Task 2.2's full local pipeline (build_close_package)
run against the real fixture contracts, mirroring tests/
test_drafter_integration.py's own pattern one level up: analysis ->
synthesis -> schedule extraction -> schedule computation -> audit trail
-> package assembly, all on real fixture text, with a fake LLM client
keyed by contract content.

Two things worth proving beyond what test_drafter_integration.py already
covers: (1) the whole chain actually runs end to end and produces a
package_html containing all three sections; (2) the over-time SaaS
obligation's schedule genuinely reconstructs its own allocated dollar
amount when summed across its monthly entries -- the one place real
arithmetic happens in this project.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from close_package.runner import build_close_package

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "drafter"


class _FixtureAwareFakeLLMClient:
    """Same shape as tests/test_drafter_integration.py's fake client, plus
    extract_recognition_schedule_facts -- every source_quote below is
    copied verbatim from the actual fixture text."""

    def analyze_revenue_recognition(
        self, contract_text: str, idem_key: str | None = None
    ) -> dict[str, Any]:
        if "Northstar Analytics" in contract_text:
            return self._saas_analysis()
        if "Precision Robotics" in contract_text:
            return self._hardware_analysis()
        raise AssertionError(f"unexpected contract text: {contract_text[:80]!r}")

    def extract_recognition_schedule_facts(
        self, contract_text: str, obligations_context: str, idem_key: str | None = None
    ) -> list[dict[str, Any]]:
        if "Northstar Analytics" in contract_text:
            return [
                {
                    "obligation_id": "platform_access",
                    "term_start_description": "the Effective Date",
                    "term_length_months": 12,
                    "source_quote": "twelve (12) months beginning on the Effective Date",
                }
            ]
        if "Precision Robotics" in contract_text:
            return [
                {
                    "obligation_id": "extended_warranty",
                    "term_start_description": "acceptance of the Equipment",
                    "term_length_months": 36,
                    "source_quote": "continuing for thirty-six (36) months thereafter",
                }
            ]
        raise AssertionError(f"unexpected contract text: {contract_text[:80]!r}")

    def _saas_analysis(self) -> dict[str, Any]:
        return {
            "performance_obligations": [
                {
                    "obligation_id": "platform_access",
                    "description": "Access to the analytics platform",
                    "source_quote": "access to the Northstar Analytics Platform",
                    "is_distinct": True,
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "onboarding",
                    "description": "One-time onboarding package",
                    "source_quote": (
                        "one-time onboarding package consisting of initial "
                        "data migration, account configuration, and two (2) "
                        "training sessions"
                    ),
                    "is_distinct": True,
                    "is_judgement": False,
                    "judgement_note": "",
                },
            ],
            "price_allocations": [
                {
                    "obligation_id": "platform_access",
                    "allocated_amount": "$84,000",
                    "allocation_basis": "stated explicitly in contract",
                    "source_quote": (
                        "the remaining $84,000 is allocated to Platform "
                        "Access inclusive of Premium Support, billed "
                        "ratably over the Term"
                    ),
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "onboarding",
                    "allocated_amount": "$12,000",
                    "allocation_basis": "stated explicitly in contract",
                    "source_quote": "$12,000 is specifically allocated to Onboarding Services",
                    "is_judgement": False,
                    "judgement_note": "",
                },
            ],
            "timing_conclusions": [
                {
                    "obligation_id": "platform_access",
                    "recognition_pattern": "over_time",
                    "timing_basis": "customer benefits continuously throughout the subscription term",
                    "source_quote": "twelve (12) months beginning on the Effective Date",
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "onboarding",
                    "recognition_pattern": "point_in_time",
                    "timing_basis": "recognized upon completion of the onboarding deliverables",
                    "source_quote": "completed within thirty (30) days of the Effective Date",
                    "is_judgement": False,
                    "judgement_note": "",
                },
            ],
        }

    def _hardware_analysis(self) -> dict[str, Any]:
        return {
            "performance_obligations": [
                {
                    "obligation_id": "equipment",
                    "description": "Six Model PR-4400 automated packaging units",
                    "source_quote": (
                        "manufacture, deliver, and install six (6) Model "
                        "PR-4400 automated packaging units"
                    ),
                    "is_distinct": True,
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "extended_warranty",
                    "description": "Three-year extended warranty",
                    "source_quote": (
                        "provide a three (3) year Extended Warranty "
                        "covering parts, labor, and quarterly preventive "
                        "maintenance visits"
                    ),
                    "is_distinct": True,
                    "is_judgement": True,
                    "judgement_note": (
                        "Because the Extended Warranty is separately "
                        "priced and provides services distinct from and "
                        "in addition to the Equipment, it constitutes a "
                        "distinct performance obligation from the "
                        "Equipment sale, per the contract's own reasoning."
                    ),
                },
            ],
            "price_allocations": [
                {
                    "obligation_id": "equipment",
                    "allocated_amount": "$540,000",
                    "allocation_basis": "stated explicitly in contract",
                    "source_quote": (
                        "The purchase price for the six (6) Equipment "
                        "units, inclusive of delivery and installation, "
                        "is $540,000"
                    ),
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "extended_warranty",
                    "allocated_amount": "$81,000",
                    "allocation_basis": "stated explicitly in contract",
                    "source_quote": "The price for the three (3) year Extended Warranty is $81,000",
                    "is_judgement": False,
                    "judgement_note": "",
                },
            ],
            "timing_conclusions": [
                {
                    "obligation_id": "equipment",
                    "recognition_pattern": "point_in_time",
                    "timing_basis": "control transfers upon written acceptance following installation",
                    "source_quote": (
                        "Title and control of the Equipment transfer to "
                        "Buyer upon Buyer's written acceptance following "
                        "successful installation and calibration testing"
                    ),
                    "is_judgement": False,
                    "judgement_note": "",
                },
                {
                    "obligation_id": "extended_warranty",
                    "recognition_pattern": "over_time",
                    "timing_basis": "customer benefits from coverage throughout the warranty period",
                    "source_quote": "continuing for thirty-six (36) months thereafter",
                    "is_judgement": False,
                    "judgement_note": "",
                },
            ],
        }


def test_build_close_package_end_to_end_on_saas_fixture() -> None:
    llm = _FixtureAwareFakeLLMClient()
    state = build_close_package(str(FIXTURES_DIR / "contract_saas_bundled.txt"), llm)  # type: ignore[arg-type]

    # Every stage ran, in order.
    assert state["stage_log"] == [
        "analyze_contract",
        "synthesize_memo",
        "extract_schedule_facts",
        "compute_schedule_entries",
        "build_audit_trail",
        "assemble_package",
    ]

    # The schedule fact was verified against the real fixture text.
    fact = state["schedule"]["schedule_facts"][0]
    assert fact["citation_verified"] is True

    # The over-time obligation's 12 monthly entries reconstruct its own
    # $84,000 allocated amount -- the one place real arithmetic happens.
    over_time_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "platform_access"]
    assert len(over_time_entries) == 12
    total = sum(float(e["recognized_amount"].replace("$", "").replace(",", "")) for e in over_time_entries)
    assert round(total, 2) == 84000.00

    # The point-in-time obligation is a single entry for its full amount.
    onboarding_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "onboarding"]
    assert len(onboarding_entries) == 1
    assert onboarding_entries[0]["recognized_amount"] == "$12,000.00"

    # The package includes all three sections.
    assert "Revenue Recognition Memo" in state["package_html"]
    assert "Revenue Recognition Schedule" in state["package_html"]
    assert "Audit Trail" in state["package_html"]

    # The audit trail covers every category, including the new schedule_fact one.
    categories = {e["category"] for e in state["audit_trail"]}
    assert categories == {
        "performance_obligation",
        "price_allocation",
        "timing_conclusion",
        "schedule_fact",
    }


def test_build_close_package_end_to_end_on_hardware_fixture() -> None:
    llm = _FixtureAwareFakeLLMClient()
    state = build_close_package(str(FIXTURES_DIR / "contract_hardware_warranty.txt"), llm)  # type: ignore[arg-type]

    # 36-month warranty schedule reconstructs its own $81,000 allocation.
    warranty_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "extended_warranty"]
    assert len(warranty_entries) == 36
    total = sum(float(e["recognized_amount"].replace("$", "").replace(",", "")) for e in warranty_entries)
    assert round(total, 2) == 81000.00

    # The point-in-time equipment sale is a single entry.
    equipment_entries = [e for e in state["schedule"]["entries"] if e["obligation_id"] == "equipment"]
    assert len(equipment_entries) == 1
    assert equipment_entries[0]["recognized_amount"] == "$540,000.00"

    # No cross-contamination from the other fixture.
    assert "platform_access" not in state["package_html"]
