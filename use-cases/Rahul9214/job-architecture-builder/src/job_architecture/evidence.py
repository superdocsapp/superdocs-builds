"""Extract RoleEvidence from parsed Markdown job descriptions.

Extraction copies source language into dimensions. Missing dimensions are
marked with UNSTATED rather than filled with inferred prose.
"""

from __future__ import annotations

from pathlib import Path

from job_architecture.catalog import (
    AUTONOMY_SPLIT_CUES,
    COMPLEXITY_CUES,
    DECISION_CUES,
    IMPACT_CUES,
    LEADERSHIP_CUES,
    PEOPLE_MGMT_CUES,
    SCOPE_SPLIT_CUES,
)
from job_architecture.fixtures import ParsedJobDescription, parse_markdown_sections
from job_architecture.models import RoleEvidence, SourceReference
from job_architecture.textutil import (
    UNSTATED,
    count_sparse_markers,
    excerpt,
    first_matching_sentence,
    normalize_whitespace,
    parse_bullets,
    split_sentences,
    word_count,
)

SECTION_ROLE_PURPOSE = "role purpose"
SECTION_RESPONSIBILITIES = "responsibilities"
SECTION_SCOPE_AUTONOMY = "scope and autonomy"
SECTION_LEADERSHIP = "leadership and management"
SECTION_STAKEHOLDERS = "stakeholders"
SECTION_REQUIREMENTS = "requirements"
SECTION_TEAM = "team"


def _join_or_unstated(parts: list[str]) -> str:
    cleaned = [normalize_whitespace(part) for part in parts if normalize_whitespace(part)]
    if not cleaned:
        return UNSTATED
    return " ".join(cleaned)


def _ref(role_id: str, locator: str, text: str) -> SourceReference | None:
    snippet = excerpt(text)
    if not snippet or snippet == UNSTATED:
        return None
    return SourceReference(document_id=role_id, locator=locator, excerpt=snippet)


def _split_scope_autonomy(section: str) -> tuple[str, str]:
    sentences = split_sentences(section)
    scope_parts = first_matching_sentence(sentences, SCOPE_SPLIT_CUES)
    autonomy_parts = first_matching_sentence(sentences, AUTONOMY_SPLIT_CUES)
    if not scope_parts and not autonomy_parts:
        return (normalize_whitespace(section) or UNSTATED, UNSTATED)
    if not scope_parts:
        scope_parts = [sentence for sentence in sentences if sentence not in autonomy_parts]
    if not autonomy_parts:
        autonomy_parts = [sentence for sentence in sentences if sentence not in scope_parts]
    return (_join_or_unstated(scope_parts), _join_or_unstated(autonomy_parts))


def _split_leadership(section: str) -> tuple[str, str]:
    sentences = split_sentences(section)
    people_parts = first_matching_sentence(sentences, PEOPLE_MGMT_CUES)
    lead_parts = first_matching_sentence(sentences, LEADERSHIP_CUES)
    leftover = [
        sentence
        for sentence in sentences
        if sentence not in people_parts and sentence not in lead_parts
    ]
    if not people_parts and not lead_parts:
        text = normalize_whitespace(section) or UNSTATED
        return (text, text)
    if leftover:
        lead_parts = lead_parts + leftover
    leadership = _join_or_unstated(lead_parts)
    people = _join_or_unstated(people_parts)
    return (leadership, people)


def extract_role_evidence(parsed: ParsedJobDescription, organization: str) -> RoleEvidence:
    purpose = parsed.section(SECTION_ROLE_PURPOSE)
    responsibilities_text = parsed.section(SECTION_RESPONSIBILITIES)
    scope_autonomy_text = parsed.section(SECTION_SCOPE_AUTONOMY)
    leadership_text = parsed.section(SECTION_LEADERSHIP)
    stakeholders_text = parsed.section(SECTION_STAKEHOLDERS)
    requirements_text = parsed.section(SECTION_REQUIREMENTS)
    team = parsed.section(SECTION_TEAM).splitlines()[0].strip() if parsed.section(SECTION_TEAM) else ""

    responsibilities = parse_bullets(responsibilities_text)
    scope, autonomy = _split_scope_autonomy(scope_autonomy_text)
    leadership, people_management = _split_leadership(leadership_text)

    all_sentences = (
        split_sentences(purpose)
        + split_sentences(responsibilities_text)
        + split_sentences(scope_autonomy_text)
        + split_sentences(requirements_text)
    )
    complexity = _join_or_unstated(first_matching_sentence(all_sentences, COMPLEXITY_CUES))
    impact = _join_or_unstated(
        first_matching_sentence(split_sentences(purpose) + split_sentences(scope_autonomy_text), IMPACT_CUES)
    )
    decision = _join_or_unstated(
        first_matching_sentence(split_sentences(scope_autonomy_text) + split_sentences(leadership_text), DECISION_CUES)
    )
    stakeholder_items = parse_bullets(stakeholders_text)
    stakeholder_breadth = _join_or_unstated([f"- {item}" for item in stakeholder_items]) if stakeholder_items else UNSTATED
    domain_depth = _join_or_unstated(
        [normalize_whitespace(purpose)] + parse_bullets(requirements_text)
    )

    refs: list[SourceReference] = []
    for locator, text in (
        (SECTION_TEAM, team),
        (SECTION_ROLE_PURPOSE, purpose),
        (SECTION_RESPONSIBILITIES, responsibilities_text),
        (SECTION_SCOPE_AUTONOMY, scope_autonomy_text),
        (SECTION_LEADERSHIP, leadership_text),
        (SECTION_STAKEHOLDERS, stakeholders_text),
        (SECTION_REQUIREMENTS, requirements_text),
    ):
        ref = _ref(parsed.role_id, locator, text)
        if ref is not None:
            refs.append(ref)

    return RoleEvidence(
        role_id=parsed.role_id,
        title=parsed.title,
        organization=organization,
        team=team,
        responsibilities=responsibilities,
        scope=scope,
        autonomy=autonomy,
        complexity=complexity,
        impact=impact,
        leadership=leadership,
        people_management=people_management,
        stakeholder_breadth=stakeholder_breadth,
        domain_depth=domain_depth,
        decision_making_authority=decision if decision != UNSTATED else "",
        source_references=refs,
    )


def evidence_from_markdown(
    markdown: str,
    *,
    role_id: str,
    organization: str,
) -> RoleEvidence:
    title, sections = parse_markdown_sections(markdown)
    parsed = ParsedJobDescription(
        role_id=role_id,
        path=Path(f"{role_id}.md"),
        title=title,
        raw_markdown=markdown,
        sections=sections,
    )
    return extract_role_evidence(parsed, organization)


def is_sparse_evidence(evidence: RoleEvidence, raw_markdown: str | None = None) -> bool:
    body = " ".join(
        [
            *evidence.responsibilities,
            evidence.scope,
            evidence.autonomy,
            evidence.domain_depth,
            evidence.people_management,
            evidence.leadership,
        ]
    )
    source = raw_markdown or body
    markers = count_sparse_markers(source)
    words = word_count(body)
    unstated_count = sum(
        1
        for value in (
            evidence.scope,
            evidence.autonomy,
            evidence.complexity,
            evidence.impact,
            evidence.leadership,
            evidence.people_management,
        )
        if value == UNSTATED or word_count(value) <= 4
    )
    return markers >= 3 or words < 70 or unstated_count >= 4


def scoring_text(evidence: RoleEvidence) -> str:
    """Body text used for family scoring. Title and stakeholders are excluded.

    Stakeholders describe who the role talks to, not what family the work is.
    """
    parts = [
        *evidence.responsibilities,
        evidence.scope,
        evidence.autonomy,
        evidence.complexity if evidence.complexity != UNSTATED else "",
        evidence.impact if evidence.impact != UNSTATED else "",
        evidence.leadership if evidence.leadership != UNSTATED else "",
        evidence.people_management if evidence.people_management != UNSTATED else "",
        evidence.domain_depth if evidence.domain_depth != UNSTATED else "",
        evidence.decision_making_authority,
    ]
    return " ".join(part for part in parts if part)
