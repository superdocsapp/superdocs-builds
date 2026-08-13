"""Tests for close_package/assemble.py. Pure deterministic string
assembly -- no LLM involved. The load-bearing guarantees: the memo HTML
passes through untouched, every schedule/audit-trail entry is rendered
(including flagged ones -- nothing silently dropped), and flagged rows
carry a visible marker.
"""

from __future__ import annotations

from close_package.assemble import assemble_package, render_audit_trail_html, render_schedule_html
from close_package.state import AuditTrailEntry, ClosePackageState, ScheduleEntry
from drafter.state import DrafterState, MemoAnalysis


def _schedule_entry(**overrides: object) -> ScheduleEntry:
    base: ScheduleEntry = {
        "obligation_id": "platform_access",
        "period_label": "Month 1 of 12",
        "recognized_amount": "$7,000.00",
        "basis": "straight_line_over_time",
        "requires_human_review": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _audit_entry(**overrides: object) -> AuditTrailEntry:
    base: AuditTrailEntry = {
        "category": "performance_obligation",
        "subject": "platform_access",
        "conclusion": "Access to the platform -- distinct",
        "source_quote": "access to the Platform",
        "citation_verified": True,
        "is_judgement": False,
        "judgement_note": "",
        "requires_human_review": False,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return base


def _state(schedule_entries: list[ScheduleEntry], audit_trail: list[AuditTrailEntry]) -> ClosePackageState:
    analysis: MemoAnalysis = {
        "contract_filename": "contract.txt",
        "performance_obligations": [],
        "price_allocations": [],
        "timing_conclusions": [],
    }
    memo_state: DrafterState = {
        "run_id": "cp-test",
        "contract_path": "contract.txt",
        "contract_text": "irrelevant",
        "contract_filename": "contract.txt",
        "analysis": analysis,
        "judgement_notes": [],
        "memo_html": "<h1>Revenue Recognition Memo</h1><p>stub memo body</p>",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": [],
    }
    return {
        "run_id": "cp-test",
        "memo_state": memo_state,
        "schedule": {
            "contract_filename": "contract.txt",
            "schedule_facts": [],
            "entries": schedule_entries,
        },
        "audit_trail": audit_trail,
        "package_html": "",
        "session_id": "",
        "job_id": "",
        "export_result": {},
        "stage_log": ["analyze_contract", "synthesize_memo", "extract_schedule_facts", "compute_schedule_entries", "build_audit_trail"],
    }


def test_render_schedule_html_includes_every_entry() -> None:
    entries = [_schedule_entry(period_label="Month 1 of 12"), _schedule_entry(period_label="Month 2 of 12")]
    html = render_schedule_html(entries)
    assert "Month 1 of 12" in html
    assert "Month 2 of 12" in html


def test_render_schedule_html_flags_review_rows() -> None:
    entries = [_schedule_entry(requires_human_review=True, period_label="Full term (schedule unavailable)")]
    html = render_schedule_html(entries)
    assert "NEEDS HUMAN REVIEW" in html


def test_render_schedule_html_empty_is_explicit() -> None:
    html = render_schedule_html([])
    assert "No schedule entries" in html


def test_render_audit_trail_html_includes_every_entry() -> None:
    entries = [
        _audit_entry(subject="platform_access", category="performance_obligation"),
        _audit_entry(subject="support_services", category="price_allocation"),
    ]
    html = render_audit_trail_html(entries)
    assert "platform_access" in html
    assert "support_services" in html


def test_render_audit_trail_html_shows_verification_status() -> None:
    verified = _audit_entry(citation_verified=True, requires_human_review=False)
    unverified = _audit_entry(citation_verified=False, requires_human_review=True, subject="unverified_one")
    html = render_audit_trail_html([verified, unverified])
    assert "Verified" in html
    assert "Unverified" in html
    assert "NEEDS HUMAN REVIEW" in html


def test_render_audit_trail_html_empty_is_explicit() -> None:
    html = render_audit_trail_html([])
    assert "No audit trail entries" in html


def test_assemble_package_includes_memo_schedule_and_audit_trail() -> None:
    state = _state([_schedule_entry()], [_audit_entry()])
    result = assemble_package(state)
    package_html = result["package_html"]
    # The memo passes through untouched.
    assert "stub memo body" in package_html
    # The new sections are present.
    assert "Revenue Recognition Schedule" in package_html
    assert "Audit Trail" in package_html
    assert "platform_access" in package_html


def test_assemble_package_stage_log_appends() -> None:
    state = _state([], [])
    result = assemble_package(state)
    assert result["stage_log"][-1] == "assemble_package"
    assert result["stage_log"][0] == "analyze_contract"
