import re
from datetime import date
from sqlalchemy.orm import Session

from app.models.finding import Finding
from app.models.submittal import Submittal
from app.models.transmittal import Transmittal
from app.schemas.workflow import (
    ChatResponse,
    Citation,
    SearchResponse,
    SearchResultItem,
)
from app.services.register import get_overdue_submittals


def search_project(
    db: Session,
    project_id: str,
    query: str,
) -> SearchResponse:
    """Project-wide grounded search across submittals, findings, and transmittals."""
    q = query.strip().lower()
    if not q:
        return SearchResponse(query=query, total_count=0, results=[])

    results: list[SearchResultItem] = []

    # 1. Search Submittals
    submittals = (
        db.query(Submittal)
        .filter(Submittal.project_id == project_id)
        .all()
    )
    for s in submittals:
        match_targets = [
            s.number,
            s.title,
            s.description or "",
            s.specification_section,
            s.required_by or "",
            s.required_form or "",
            s.source_evidence or "",
            s.specification_revision or "",
            s.register_status,
        ]
        matched = next((t for t in match_targets if q in t.lower()), None)
        if matched:
            results.append(
                SearchResultItem(
                    entity_type="SUBMITTAL",
                    entity_id=s.number,
                    title=f"{s.number} — {s.title}",
                    subtitle=f"Section {s.specification_section} · {s.register_status}",
                    matched_text=matched,
                    url=f"/projects/{project_id}/submittals/{s.number}",
                )
            )

    # 2. Search Findings
    findings = (
        db.query(Finding)
        .join(Submittal, Finding.submittal_id == Submittal.id)
        .filter(Submittal.project_id == project_id)
        .all()
    )
    for f in findings:
        sub = db.query(Submittal).filter(Submittal.id == f.submittal_id).first()
        sub_num = sub.number if sub else "Unknown"
        match_targets = [
            f.attribute,
            f.requirement,
            f.submitted_value,
            f.result,
            f.specification_evidence,
            f.submission_evidence,
            f.reviewer or "",
            f.reviewer_comment or "",
        ]
        matched = next((t for t in match_targets if q in t.lower()), None)
        if matched:
            results.append(
                SearchResultItem(
                    entity_type="FINDING",
                    entity_id=f.id,
                    title=f"Finding: {f.attribute} ({f.result})",
                    subtitle=f"Submittal {sub_num} · {f.status}",
                    matched_text=matched,
                    url=f"/projects/{project_id}/submittals/{sub_num}",
                )
            )

    # 3. Search Transmittals
    transmittals = (
        db.query(Transmittal)
        .filter(Transmittal.project_id == project_id)
        .all()
    )
    for tr in transmittals:
        if q in tr.number.lower() or q in tr.status.lower():
            results.append(
                SearchResultItem(
                    entity_type="TRANSMITTAL",
                    entity_id=tr.id,
                    title=f"Transmittal {tr.number}",
                    subtitle=f"Status: {tr.status}",
                    matched_text=tr.number,
                    url=f"/transmittals/{tr.id}",
                )
            )

    return SearchResponse(
        query=query,
        total_count=len(results),
        results=results,
    )


def chat_project(
    db: Session,
    project_id: str,
    query: str,
    context_submittal_number: str | None = None,
) -> ChatResponse:
    """Contextual, evidence-grounded Q&A assistant for construction submittal workflows.

    Follows 'never bluff' principles: every answer references verified database entities
    or citations. If no evidence exists in project data, clearly states that.
    """
    q = query.strip().lower()
    citations: list[Citation] = []
    followups: list[str] = []

    submittals = (
        db.query(Submittal)
        .filter(Submittal.project_id == project_id)
        .all()
    )

    # 1. Overdue Query
    if "overdue" in q:
        overdue_items = get_overdue_submittals(db, project_id, date.today())
        if not overdue_items:
            return ChatResponse(
                query=query,
                answer="There are currently no overdue submittals for this project. All registered items are within their due dates or have been reviewed.",
                citations=[],
                suggested_followups=["Show all registered submittals", "What submittals are pending review?"],
            )
        lines = [f"There {'is' if len(overdue_items) == 1 else 'are'} {len(overdue_items)} overdue submittal(s):"]
        for item in overdue_items:
            days = (date.today() - item.due_date).days if item.due_date else 0
            lines.append(f"- **{item.number}** ({item.title}): Due {item.due_date} ({days} days overdue, assigned to {item.required_by or 'unassigned'}).")
            citations.append(
                Citation(
                    source_type="REGISTER",
                    identifier=item.number,
                    section=item.specification_section,
                    excerpt=f"Due date {item.due_date}, register status: {item.register_status}",
                )
            )
        followups = ["View the Overdue Submittals report", "Who is responsible for the overdue items?"]
        return ChatResponse(
            query=query,
            answer="\n".join(lines),
            citations=citations,
            suggested_followups=followups,
        )

    # 2. Specific Submittal context or targeted lookup
    target_submittal = None
    sub_match = re.search(r"sub[-_\s]*(\d+)", q, re.IGNORECASE)
    if sub_match:
        formatted_num = f"SUB-{int(sub_match.group(1)):03d}"
        target_submittal = next((s for s in submittals if s.number == formatted_num), None)
    elif context_submittal_number:
        target_submittal = next((s for s in submittals if s.number == context_submittal_number), None)

    # 3. Deviations / Findings Query
    if "deviation" in q or "finding" in q or "fire" in q or "thickness" in q or "warranty" in q or target_submittal:
        query_submittals = [target_submittal] if target_submittal else submittals
        all_deviations: list[tuple[Submittal, Finding]] = []
        all_findings: list[tuple[Submittal, Finding]] = []

        for s in query_submittals:
            findings = db.query(Finding).filter(Finding.submittal_id == s.id).all()
            for f in findings:
                all_findings.append((s, f))
                if f.result == "DEVIATION":
                    all_deviations.append((s, f))

        if "deviation" in q:
            if not all_deviations:
                return ChatResponse(
                    query=query,
                    answer="No deviations were found in the reviewed submittals." if all_findings else "No comparison findings have been generated yet for this submittal.",
                    citations=[],
                    suggested_followups=["Start automated submittal comparison", "View the submittal register"],
                )
            lines = [f"Identified {len(all_deviations)} deviation(s):"]
            for s, f in all_deviations:
                lines.append(
                    f"- **{s.number} ({f.attribute})**: Specified `{f.requirement}` vs Submitted `{f.submitted_value}`.\n"
                    f"  *Specification Evidence:* \"{f.specification_evidence}\"\n"
                    f"  *Submission Evidence:* \"{f.submission_evidence}\"\n"
                    f"  *Review Status:* {f.status}" + (f" by {f.reviewer}" if f.reviewer else "")
                )
                citations.append(
                    Citation(
                        source_type="SPECIFICATION",
                        identifier=s.specification_section,
                        section=s.specification_section,
                        excerpt=f.specification_evidence,
                    )
                )
                citations.append(
                    Citation(
                        source_type="SUBMITTAL",
                        identifier=s.number,
                        section=f.attribute,
                        excerpt=f.submission_evidence,
                    )
                )
            return ChatResponse(
                query=query,
                answer="\n\n".join(lines),
                citations=citations,
                suggested_followups=["How do I approve or reject this deviation?", "Generate a transmittal packet"],
            )

        # Attribute-specific query (e.g. fire rating or thickness)
        matched_findings = [
            (s, f) for s, f in all_findings
            if any(term in q for term in [f.attribute.lower(), "evidence", "rating", "thickness", "warranty"])
        ]
        if matched_findings:
            lines = []
            for s, f in matched_findings:
                lines.append(
                    f"### Finding: {f.attribute} ({f.result}) on {s.number}\n"
                    f"- **Requirement:** {f.requirement}\n"
                    f"- **Submitted Value:** {f.submitted_value}\n"
                    f"- **Specification Evidence:** \"{f.specification_evidence}\"\n"
                    f"- **Submission Evidence:** \"{f.submission_evidence}\"\n"
                    f"- **Status:** {f.status}"
                )
                citations.append(
                    Citation(
                        source_type="SPECIFICATION",
                        identifier=s.specification_section,
                        section=f.attribute,
                        excerpt=f.specification_evidence,
                    )
                )
                citations.append(
                    Citation(
                        source_type="SUBMITTAL",
                        identifier=s.number,
                        section=f.attribute,
                        excerpt=f.submission_evidence,
                    )
                )
            return ChatResponse(
                query=query,
                answer="\n\n".join(lines),
                citations=citations,
                suggested_followups=["What is the current review status?", "Export transmittal to DOCX"],
            )

    # 4. Specification section lookup / revision query
    spec_match = re.search(r"(\d{2}\s*\d{2}\s*\d{2})", q)
    if spec_match:
        raw_sec = spec_match.group(1).replace(" ", "")
        formatted_sec = f"{raw_sec[:2]} {raw_sec[2:4]} {raw_sec[4:]}"
        matched_subs = [s for s in submittals if s.specification_section.replace(" ", "") == raw_sec]
        if matched_subs:
            lines = [f"Specification Section **{formatted_sec}** applies to:"]
            for s in matched_subs:
                lines.append(f"- **{s.number}** ({s.title}): {s.specification_revision or 'Initial revision'}, required by {s.required_by or 'Contractor'}.")
                if s.source_evidence:
                    lines.append(f"  *Evidence:* \"{s.source_evidence}\"")
                citations.append(
                    Citation(
                        source_type="SPECIFICATION",
                        identifier=formatted_sec,
                        section=s.title,
                        excerpt=s.source_evidence or f"Requirement for {s.title}",
                    )
                )
            return ChatResponse(
                query=query,
                answer="\n".join(lines),
                citations=citations,
                suggested_followups=["Show comparison findings for this section", "Check if submittal is overdue"],
            )

    # 5. General fallback — grounded response
    if submittals:
        summary_lines = [
            f"DocTask project **{project_id}** currently tracks {len(submittals)} submittal item(s):",
        ]
        for s in submittals[:5]:
            summary_lines.append(f"- **{s.number}** ({s.title}): Section {s.specification_section} — {s.register_status}")
        return ChatResponse(
            query=query,
            answer="\n".join(summary_lines),
            citations=[],
            suggested_followups=[
                "Which submittals are overdue?",
                "Show all deviations across submittals",
                "What specification requirements apply to Section 09 65 00?",
            ],
        )

    return ChatResponse(
        query=query,
        answer="I couldn't find evidence for that in the project documents. Please verify the submittal number or specification section.",
        citations=[],
        suggested_followups=["Show all registered submittals", "How do I build the submittal register?"],
    )
