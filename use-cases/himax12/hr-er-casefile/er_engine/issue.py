from __future__ import annotations

from er_engine.sequence import (
    CaseFile,
    LetterKind,
    can_issue,
    outcome_summary,
)
from er_engine.superdocs_flow import FakeDocs
from er_engine.templates import fill, load_template

LETTER_MILESTONE = {
    "improvement_plan": None,
    "absence": None,
    "invite_to_hearing": "invite_to_hearing",
    "outcome": "outcome_letter",
    "appeal_response": "appeal_response",
}


def issue_letter(case: CaseFile, kind: LetterKind, docs: FakeDocs, extra: dict[str, str] | None = None) -> dict:
    ok, why = can_issue(case, kind)
    if not ok:
        case.last_refusal = why
        return {"ok": False, "refused": True, "reason": why}

    fields = {
        "employee_name": case.employee_name,
        "employee_id": case.employee_id,
        "case_id": case.case_id,
        "chronology": "\n".join(f"- {line}" for line in case.chronology) or "- (none yet)",
        "employee_verbatim": "",
        **(extra or {}),
    }
    if kind == "outcome":
        fields["employee_verbatim"] = outcome_summary(case)

    body = fill(load_template(kind), **fields)
    doc_id = f"{case.case_id}-{kind}"
    docs.upload(doc_id, body)
    chat = docs.chat(doc_id, f"Format the {kind} letter on the approved template; do not paraphrase quoted employee speech.")
    changes = chat.get("changes") or []
    for ch in changes:
        docs.approve(doc_id, ch["change_id"], True)
    exported = docs.export(doc_id)
    case.letters[kind] = body
    milestone = LETTER_MILESTONE[kind]
    if milestone:
        case.done.add(milestone)
    case.chronology.append(f"Issued {kind.replace('_', ' ')} letter.")
    case.last_refusal = None
    return {
        "ok": True,
        "refused": False,
        "doc_id": doc_id,
        "export_format": exported["format"],
        "body": body,
    }


def render_casefile(case: CaseFile) -> str:
    tpl = load_template("casefile")
    return fill(
        tpl,
        employee_name=case.employee_name,
        employee_id=case.employee_id,
        case_id=case.case_id,
        chronology="\n".join(f"- {line}" for line in case.chronology),
        employee_verbatim=case.employee_verbatim or "(not yet recorded)",
    )
