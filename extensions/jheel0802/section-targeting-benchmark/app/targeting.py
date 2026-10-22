from __future__ import annotations

from typing import Any


PUBLIC_FAILURE_DEFINITIONS = {
    "Wrong target": "SuperDocs selected the wrong section.",
    "Should have clarified": "The request was genuinely ambiguous, but SuperDocs guessed.",
    "Unsupported target": "The document did not support the request, but SuperDocs still selected or used content.",
    "Right target, wrong result": "SuperDocs identified the correct section, but the answer or edit was incorrect or incomplete.",
}

# Evidence-reviewed exceptions among the 15 strict failures in frozen run 2.
# Every entry is supported by the stored response/change path and reviewer note;
# old taxonomy names are deliberately not used as the decision rule.
REVIEWED_STRICT_FAILURES: dict[str, tuple[str, str, str | None]] = {
    "D01-C02": ("fail", "Proposed edit targeted Northstar Health > Risks instead of Harbor Retail > Risks.", "Wrong target"),
    "D01-C03": ("fail", "The request had two valid Timeline targets, but the response selected one without clarification.", "Should have clarified"),
    "D02-C01": ("pass", "The response used Web Application > Deployment Window but omitted the window end time.", "Right target, wrong result"),
    "D02-C02": ("pass", "The changed chunk contains the Mobile Applications rollback instructions; the edit removed required content.", "Right target, wrong result"),
    "D03-C02": ("fail", "The edit used Beacon Desk summary/body text instead of Beacon Desk > Security Assessment.", "Wrong target"),
    "D04-C01": ("pass", "The reviewer confirmed the Root Cause section was identified, but the answer omitted part of the cause.", "Right target, wrong result"),
    "D05-C02": ("fail", "The proposal targeted 2.2 Empty and Error States instead of 3.2 User Lifecycle.", "Wrong target"),
    "D08-C03": ("pass", "The response identified Phase 4 Exit Criteria but did not return the required result correctly.", "Right target, wrong result"),
    "D09-C02": ("fail", "The location was ambiguous, but the proposal selected the United Kingdom policy without clarification.", "Should have clarified"),
    "D10-C02": ("fail", "The proposal targeted Security > Audit instead of Logical Architecture > Replay Service.", "Wrong target"),
    "D10-C03": ("fail", "The requested disaster-recovery target was absent, but the response supplied unsupported values.", "Unsupported target"),
    "D12-C01": ("ambiguous", "The response promised to inspect remediation dates but returned neither an answer nor observable section evidence.", None),
    "D12-C02": ("fail", "The proposal targeted Change Management > Test Results instead of Change Management > Finding.", "Wrong target"),
    "D12-C03": ("fail", "The requested remediation owner was absent, but the response invented a remediation plan.", "Unsupported target"),
    "D13-C01": ("pass", "The response addressed the Training Capacity decision but returned the wrong committee decision.", "Right target, wrong result"),
}

FAILURE_CATEGORY_GROUPS = {
    "wrong_target": ("fail", "Wrong target"), "wrong_duplicate": ("fail", "Wrong target"),
    "parent_context_ignored": ("fail", "Wrong target"), "semantic_reference_miss": ("fail", "Wrong target"),
    "body_text_confusion": ("fail", "Wrong target"), "ordinal_reference_error": ("fail", "Wrong target"),
    "relative_position_error": ("fail", "Wrong target"), "historical_current_confusion": ("fail", "Wrong target"),
    "appendix_confusion": ("fail", "Wrong target"), "over_targeting": ("fail", "Wrong target"),
    "under_targeting": ("fail", "Wrong target"), "lexical_normalization_failure": ("fail", "Wrong target"),
    "instruction_scoping_failure": ("fail", "Wrong target"), "cross_reference_confusion": ("fail", "Wrong target"),
    "should_have_clarified": ("fail", "Should have clarified"), "failed_to_clarify": ("fail", "Should have clarified"),
    "unnecessary_clarification": ("fail", "Should have clarified"),
    "unsupported_target": ("fail", "Unsupported target"), "no_target_but_modified": ("fail", "Unsupported target"),
    "right_target_wrong_result": ("pass", "Right target, wrong result"),
    "correct_section_wrong_answer": ("pass", "Right target, wrong result"),
    "correct_section_wrong_edit_range": ("pass", "Right target, wrong result"),
}


def simplify_failure_category(category: str | None) -> str | None:
    mapped = FAILURE_CATEGORY_GROUPS.get(category or "")
    return mapped[1] if mapped else ("Other" if category == "other" else None)


def assess_targeting(row: dict[str, Any]) -> dict[str, Any]:
    strict = row.get("strict_verdict") or row.get("verdict")
    case_id = row.get("external_case_id") or row.get("case_id")
    # Targeting is a reviewer-derived view of the original adjudication.  A
    # freshly executed attempt must remain unscored even when its case ID also
    # exists in the evidence-reviewed frozen run.
    if strict not in {"pass", "fail", "ambiguous"}:
        return {"targeting_verdict": None, "targeting_reason": None, "simplified_failure_category": None}
    if strict == "pass":
        return {"targeting_verdict": "pass", "targeting_reason": "The strict adjudication passed, which includes correct first-attempt targeting.", "simplified_failure_category": None}
    failure_category = row.get("failure_category")
    mapped = FAILURE_CATEGORY_GROUPS.get(failure_category or "")
    if strict == "fail" and mapped:
        verdict, category = mapped
        return {"targeting_verdict": verdict, "targeting_reason": f"Reviewer classified this as {category.lower()}.", "simplified_failure_category": category}
    if strict == "fail" and failure_category == "other":
        return {"targeting_verdict": "ambiguous", "targeting_reason": "The reviewer selected Other, so targeting cannot be derived safely.", "simplified_failure_category": None}
    reviewed = REVIEWED_STRICT_FAILURES.get(str(case_id))
    if reviewed:
        verdict, reason, category = reviewed
        return {"targeting_verdict": verdict, "targeting_reason": reason, "simplified_failure_category": category}
    return {"targeting_verdict": "ambiguous", "targeting_reason": "Historical evidence was insufficient for a safe targeting classification.", "simplified_failure_category": None}


def verdict_summary(rows: list[dict[str, Any]], field: str) -> dict[str, Any]:
    scored=[r for r in rows if r.get(field) in {"pass", "fail", "ambiguous"}]
    total=len(scored); passed=sum(r.get(field)=="pass" for r in scored); failed=sum(r.get(field)=="fail" for r in scored); cannot=sum(r.get(field)=="ambiguous" for r in scored)
    return {"total":total,"pass":passed,"fail":failed,"cannot_determine":cannot,"accuracy":passed/total if total else 0}
