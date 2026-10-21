"""Typed domain models for evidence-based job architecture.

Models serialize to and from plain JSON-compatible dicts. Construction
validates constrained fields. No SuperDocs client or API key is required.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


def _require_str(value: Any, field_name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    stripped = value.strip()
    if not allow_empty and not stripped:
        raise ValueError(f"{field_name} must be a non-empty string")
    return stripped


def _optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_str(value, field_name)


def _require_str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    items = [item.strip() for item in value]
    if any(not item for item in items):
        raise ValueError(f"{field_name} must not contain empty strings")
    return items


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


class FitStatus(StrEnum):
    STRONG_FIT = "strong_fit"
    PROVISIONAL = "provisional"
    MISFIT = "misfit"


class CareerTrackKind(StrEnum):
    INDIVIDUAL_CONTRIBUTOR = "individual_contributor"
    PEOPLE_MANAGER = "people_manager"


class TitleConflictKind(StrEnum):
    TITLE_SENIORITY_OVERSTATES_EVIDENCE = "title_seniority_overstates_evidence"
    TITLE_MANAGEMENT_CONFLICT = "title_management_conflict"
    TITLE_UNDERSTATES_SCOPE = "title_understates_scope"


def parse_title_conflict_kind(value: Any, field_name: str = "kind") -> TitleConflictKind:
    if isinstance(value, TitleConflictKind):
        return value
    raw = _require_str(value, field_name)
    try:
        return TitleConflictKind(raw)
    except ValueError as exc:
        allowed = ", ".join(kind.value for kind in TitleConflictKind)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def parse_fit_status(value: Any, field_name: str = "fit_status") -> FitStatus:
    if isinstance(value, FitStatus):
        return value
    raw = _require_str(value, field_name)
    try:
        return FitStatus(raw)
    except ValueError as exc:
        allowed = ", ".join(status.value for status in FitStatus)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


def parse_track_kind(value: Any, field_name: str = "kind") -> CareerTrackKind:
    if isinstance(value, CareerTrackKind):
        return value
    raw = _require_str(value, field_name)
    try:
        return CareerTrackKind(raw)
    except ValueError as exc:
        allowed = ", ".join(kind.value for kind in CareerTrackKind)
        raise ValueError(f"{field_name} must be one of: {allowed}") from exc


@dataclass(frozen=True)
class SourceReference:
    """Pointer back to a source job-description passage."""

    document_id: str
    locator: str
    excerpt: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "document_id", _require_str(self.document_id, "document_id"))
        object.__setattr__(self, "locator", _require_str(self.locator, "locator"))
        excerpt = self.excerpt
        if excerpt is not None:
            object.__setattr__(self, "excerpt", _require_str(excerpt, "excerpt"))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "document_id": self.document_id,
            "locator": self.locator,
        }
        if self.excerpt is not None:
            payload["excerpt"] = self.excerpt
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SourceReference:
        payload = _require_mapping(data, "source_reference")
        return cls(
            document_id=payload.get("document_id"),
            locator=payload.get("locator"),
            excerpt=payload.get("excerpt"),
        )


def _parse_source_references(value: Any, field_name: str) -> list[SourceReference]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    refs: list[SourceReference] = []
    for index, item in enumerate(value):
        if isinstance(item, SourceReference):
            refs.append(item)
            continue
        try:
            refs.append(SourceReference.from_dict(item))
        except ValueError as exc:
            raise ValueError(f"{field_name}[{index}]: {exc}") from exc
    return refs


@dataclass(frozen=True)
class RoleEvidence:
    """Evidence dimensions extracted from a job description.

    Titles are recorded but are never sufficient on their own for family
    or level assignment.
    """

    role_id: str
    title: str
    organization: str
    responsibilities: list[str]
    scope: str
    autonomy: str
    complexity: str
    impact: str
    leadership: str
    people_management: str
    stakeholder_breadth: str
    domain_depth: str
    source_references: list[SourceReference]
    team: str = ""
    decision_making_authority: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_id", _require_str(self.role_id, "role_id"))
        object.__setattr__(self, "title", _require_str(self.title, "title"))
        object.__setattr__(self, "organization", _require_str(self.organization, "organization"))
        object.__setattr__(
            self,
            "responsibilities",
            _require_str_list(list(self.responsibilities), "responsibilities"),
        )
        object.__setattr__(self, "scope", _require_str(self.scope, "scope"))
        object.__setattr__(self, "autonomy", _require_str(self.autonomy, "autonomy"))
        object.__setattr__(self, "complexity", _require_str(self.complexity, "complexity"))
        object.__setattr__(self, "impact", _require_str(self.impact, "impact"))
        object.__setattr__(self, "leadership", _require_str(self.leadership, "leadership"))
        object.__setattr__(
            self,
            "people_management",
            _require_str(self.people_management, "people_management"),
        )
        object.__setattr__(
            self,
            "stakeholder_breadth",
            _require_str(self.stakeholder_breadth, "stakeholder_breadth"),
        )
        object.__setattr__(self, "domain_depth", _require_str(self.domain_depth, "domain_depth"))
        object.__setattr__(
            self,
            "source_references",
            _parse_source_references(list(self.source_references), "source_references"),
        )
        object.__setattr__(self, "team", _require_str(self.team, "team", allow_empty=True))
        object.__setattr__(
            self,
            "decision_making_authority",
            _require_str(
                self.decision_making_authority,
                "decision_making_authority",
                allow_empty=True,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "title": self.title,
            "organization": self.organization,
            "team": self.team,
            "responsibilities": list(self.responsibilities),
            "scope": self.scope,
            "autonomy": self.autonomy,
            "complexity": self.complexity,
            "impact": self.impact,
            "leadership": self.leadership,
            "people_management": self.people_management,
            "stakeholder_breadth": self.stakeholder_breadth,
            "domain_depth": self.domain_depth,
            "decision_making_authority": self.decision_making_authority,
            "source_references": [ref.to_dict() for ref in self.source_references],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RoleEvidence:
        payload = _require_mapping(data, "role_evidence")
        return cls(
            role_id=payload.get("role_id"),
            title=payload.get("title"),
            organization=payload.get("organization"),
            team=payload.get("team") or "",
            responsibilities=payload.get("responsibilities"),
            scope=payload.get("scope"),
            autonomy=payload.get("autonomy"),
            complexity=payload.get("complexity"),
            impact=payload.get("impact"),
            leadership=payload.get("leadership"),
            people_management=payload.get("people_management"),
            stakeholder_breadth=payload.get("stakeholder_breadth"),
            domain_depth=payload.get("domain_depth"),
            decision_making_authority=payload.get("decision_making_authority") or "",
            source_references=payload.get("source_references") or [],
        )


@dataclass(frozen=True)
class JobFamily:
    id: str
    name: str
    description: str
    typical_domains: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "name", _require_str(self.name, "name"))
        object.__setattr__(self, "description", _require_str(self.description, "description"))
        object.__setattr__(
            self,
            "typical_domains",
            _require_str_list(list(self.typical_domains), "typical_domains"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "typical_domains": list(self.typical_domains),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JobFamily:
        payload = _require_mapping(data, "job_family")
        return cls(
            id=payload.get("id"),
            name=payload.get("name"),
            description=payload.get("description"),
            typical_domains=payload.get("typical_domains") or [],
        )


@dataclass(frozen=True)
class CareerTrack:
    id: str
    family_id: str
    kind: CareerTrackKind
    name: str
    description: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "family_id", _require_str(self.family_id, "family_id"))
        object.__setattr__(self, "kind", parse_track_kind(self.kind))
        object.__setattr__(self, "name", _require_str(self.name, "name"))
        object.__setattr__(self, "description", _require_str(self.description, "description"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_id": self.family_id,
            "kind": self.kind.value,
            "name": self.name,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CareerTrack:
        payload = _require_mapping(data, "career_track")
        return cls(
            id=payload.get("id"),
            family_id=payload.get("family_id"),
            kind=payload.get("kind"),
            name=payload.get("name"),
            description=payload.get("description"),
        )


@dataclass(frozen=True)
class LevelDefinition:
    id: str
    family_id: str
    track_id: str
    label: str
    rank: int
    scope: str
    autonomy: str
    impact: str
    leadership: str
    people_management: str = ""
    complexity: str = ""
    decision_authority: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "family_id", _require_str(self.family_id, "family_id"))
        object.__setattr__(self, "track_id", _require_str(self.track_id, "track_id"))
        object.__setattr__(self, "label", _require_str(self.label, "label"))
        if not isinstance(self.rank, int) or isinstance(self.rank, bool):
            raise ValueError("rank must be an integer")
        if self.rank < 0:
            raise ValueError("rank must be >= 0")
        object.__setattr__(self, "scope", _require_str(self.scope, "scope"))
        object.__setattr__(self, "autonomy", _require_str(self.autonomy, "autonomy"))
        object.__setattr__(self, "impact", _require_str(self.impact, "impact"))
        object.__setattr__(self, "leadership", _require_str(self.leadership, "leadership"))
        object.__setattr__(
            self,
            "people_management",
            _require_str(self.people_management, "people_management", allow_empty=True),
        )
        object.__setattr__(
            self,
            "complexity",
            _require_str(self.complexity, "complexity", allow_empty=True),
        )
        object.__setattr__(
            self,
            "decision_authority",
            _require_str(self.decision_authority, "decision_authority", allow_empty=True),
        )
        if not isinstance(self.version, int) or isinstance(self.version, bool) or self.version < 1:
            raise ValueError("version must be an integer >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_id": self.family_id,
            "track_id": self.track_id,
            "label": self.label,
            "rank": self.rank,
            "scope": self.scope,
            "autonomy": self.autonomy,
            "impact": self.impact,
            "leadership": self.leadership,
            "people_management": self.people_management,
            "complexity": self.complexity,
            "decision_authority": self.decision_authority,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LevelDefinition:
        payload = _require_mapping(data, "level_definition")
        rank = payload.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int):
            raise ValueError("rank must be an integer")
        version = payload.get("version", 1)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("version must be an integer >= 1")
        return cls(
            id=payload.get("id"),
            family_id=payload.get("family_id"),
            track_id=payload.get("track_id"),
            label=payload.get("label"),
            rank=rank,
            scope=payload.get("scope"),
            autonomy=payload.get("autonomy"),
            impact=payload.get("impact"),
            leadership=payload.get("leadership"),
            people_management=payload.get("people_management") or "",
            complexity=payload.get("complexity") or "",
            decision_authority=payload.get("decision_authority") or "",
            version=version,
        )


@dataclass(frozen=True)
class Competency:
    id: str
    family_id: str
    name: str
    description: str
    indicators_by_level: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "family_id", _require_str(self.family_id, "family_id"))
        object.__setattr__(self, "name", _require_str(self.name, "name"))
        object.__setattr__(self, "description", _require_str(self.description, "description"))
        raw = self.indicators_by_level
        if not isinstance(raw, dict):
            raise ValueError("indicators_by_level must be an object")
        parsed: dict[str, list[str]] = {}
        for key, value in raw.items():
            level_id = _require_str(key, "indicators_by_level key")
            parsed[level_id] = _require_str_list(value, f"indicators_by_level[{level_id}]")
        object.__setattr__(self, "indicators_by_level", parsed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "family_id": self.family_id,
            "name": self.name,
            "description": self.description,
            "indicators_by_level": {
                level_id: list(indicators)
                for level_id, indicators in self.indicators_by_level.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Competency:
        payload = _require_mapping(data, "competency")
        return cls(
            id=payload.get("id"),
            family_id=payload.get("family_id"),
            name=payload.get("name"),
            description=payload.get("description"),
            indicators_by_level=payload.get("indicators_by_level") or {},
        )


@dataclass(frozen=True)
class MisfitReason:
    code: str
    summary: str
    detail: str = ""
    source_references: list[SourceReference] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _require_str(self.code, "code"))
        object.__setattr__(self, "summary", _require_str(self.summary, "summary"))
        object.__setattr__(self, "detail", _require_str(self.detail, "detail", allow_empty=True))
        object.__setattr__(
            self,
            "source_references",
            _parse_source_references(list(self.source_references), "source_references"),
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "summary": self.summary,
            "detail": self.detail,
            "source_references": [ref.to_dict() for ref in self.source_references],
        }
        return payload

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MisfitReason:
        payload = _require_mapping(data, "misfit_reason")
        return cls(
            code=payload.get("code"),
            summary=payload.get("summary"),
            detail=payload.get("detail") or "",
            source_references=payload.get("source_references") or [],
        )


def _parse_misfit_reasons(value: Any, field_name: str) -> list[MisfitReason]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    reasons: list[MisfitReason] = []
    for index, item in enumerate(value):
        if isinstance(item, MisfitReason):
            reasons.append(item)
            continue
        try:
            reasons.append(MisfitReason.from_dict(item))
        except ValueError as exc:
            raise ValueError(f"{field_name}[{index}]: {exc}") from exc
    return reasons


@dataclass(frozen=True)
class TitleConflict:
    """Title-vs-evidence mismatch. Title never sets family, track, or level."""

    kind: TitleConflictKind
    summary: str
    title_signal: str
    evidence_result: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", parse_title_conflict_kind(self.kind))
        object.__setattr__(self, "summary", _require_str(self.summary, "summary"))
        object.__setattr__(self, "title_signal", _require_str(self.title_signal, "title_signal"))
        object.__setattr__(self, "evidence_result", _require_str(self.evidence_result, "evidence_result"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "summary": self.summary,
            "title_signal": self.title_signal,
            "evidence_result": self.evidence_result,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TitleConflict:
        payload = _require_mapping(data, "title_conflict")
        return cls(
            kind=payload.get("kind"),
            summary=payload.get("summary"),
            title_signal=payload.get("title_signal"),
            evidence_result=payload.get("evidence_result"),
        )


def _parse_title_conflict(value: Any, field_name: str) -> TitleConflict | None:
    if value is None:
        return None
    if isinstance(value, TitleConflict):
        return value
    try:
        return TitleConflict.from_dict(value)
    except ValueError as exc:
        raise ValueError(f"{field_name}: {exc}") from exc


@dataclass(frozen=True)
class RoleAssessment:
    """Proposed architecture assignment for a single role."""

    role_id: str
    fit_status: FitStatus
    confidence: float
    proposed_family: str | None = None
    proposed_track: str | None = None
    proposed_level: str | None = None
    supporting_evidence: list[str] = field(default_factory=list)
    counter_evidence: list[str] = field(default_factory=list)
    misfit_reasons: list[MisfitReason] = field(default_factory=list)
    title_conflict: TitleConflict | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_id", _require_str(self.role_id, "role_id"))
        object.__setattr__(self, "fit_status", parse_fit_status(self.fit_status))
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be a number")
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0 inclusive")
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(
            self,
            "proposed_family",
            _optional_str(self.proposed_family, "proposed_family"),
        )
        object.__setattr__(
            self,
            "proposed_track",
            _optional_str(self.proposed_track, "proposed_track"),
        )
        object.__setattr__(
            self,
            "proposed_level",
            _optional_str(self.proposed_level, "proposed_level"),
        )
        object.__setattr__(
            self,
            "supporting_evidence",
            _require_str_list(list(self.supporting_evidence), "supporting_evidence"),
        )
        object.__setattr__(
            self,
            "counter_evidence",
            _require_str_list(list(self.counter_evidence), "counter_evidence"),
        )
        object.__setattr__(
            self,
            "misfit_reasons",
            _parse_misfit_reasons(list(self.misfit_reasons), "misfit_reasons"),
        )
        object.__setattr__(self, "title_conflict", _parse_title_conflict(self.title_conflict, "title_conflict"))
        if self.fit_status is FitStatus.STRONG_FIT and self.proposed_family is None:
            raise ValueError("strong_fit assessments require proposed_family")
        if self.fit_status is FitStatus.MISFIT and not self.misfit_reasons:
            raise ValueError("misfit assessments require at least one misfit reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "proposed_family": self.proposed_family,
            "proposed_track": self.proposed_track,
            "proposed_level": self.proposed_level,
            "confidence": self.confidence,
            "fit_status": self.fit_status.value,
            "supporting_evidence": list(self.supporting_evidence),
            "counter_evidence": list(self.counter_evidence),
            "misfit_reasons": [reason.to_dict() for reason in self.misfit_reasons],
            "title_conflict": None if self.title_conflict is None else self.title_conflict.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RoleAssessment:
        payload = _require_mapping(data, "role_assessment")
        return cls(
            role_id=payload.get("role_id"),
            proposed_family=payload.get("proposed_family"),
            proposed_track=payload.get("proposed_track"),
            proposed_level=payload.get("proposed_level"),
            confidence=payload.get("confidence"),
            fit_status=payload.get("fit_status"),
            supporting_evidence=payload.get("supporting_evidence") or [],
            counter_evidence=payload.get("counter_evidence") or [],
            misfit_reasons=payload.get("misfit_reasons") or [],
            title_conflict=payload.get("title_conflict"),
        )


PROFILE_SECTION_IDS = (
    "title",
    "family",
    "track",
    "level",
    "purpose",
    "responsibilities",
    "scope_decision_making",
    "core_competencies",
    "level_expectations",
    "progression",
    "evidence_note",
    "classification",
)


@dataclass(frozen=True)
class RoleProfile:
    """Employee-readable profile derived from an assessed role.

    Sections are structured fields. Propagation must use section ids, not
    string-search of rendered prose.
    """

    id: str
    role_id: str
    family_id: str
    track_id: str
    level_id: str
    display_title: str
    summary: str
    responsibilities: list[str]
    competency_ids: list[str] = field(default_factory=list)
    family_name: str = ""
    track_name: str = ""
    level_label: str = ""
    classification: str = "strong_fit"
    scope_decision_making: str = ""
    core_competencies: str = ""
    level_expectations: str = ""
    progression: str = ""
    evidence_note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "role_id", _require_str(self.role_id, "role_id"))
        object.__setattr__(self, "family_id", _require_str(self.family_id, "family_id"))
        object.__setattr__(self, "track_id", _require_str(self.track_id, "track_id"))
        object.__setattr__(self, "level_id", _require_str(self.level_id, "level_id"))
        object.__setattr__(self, "display_title", _require_str(self.display_title, "display_title"))
        object.__setattr__(self, "summary", _require_str(self.summary, "summary"))
        object.__setattr__(
            self,
            "responsibilities",
            _require_str_list(list(self.responsibilities), "responsibilities"),
        )
        object.__setattr__(
            self,
            "competency_ids",
            _require_str_list(list(self.competency_ids), "competency_ids"),
        )
        object.__setattr__(self, "family_name", _require_str(self.family_name, "family_name", allow_empty=True))
        object.__setattr__(self, "track_name", _require_str(self.track_name, "track_name", allow_empty=True))
        object.__setattr__(self, "level_label", _require_str(self.level_label, "level_label", allow_empty=True))
        object.__setattr__(
            self,
            "classification",
            _require_str(self.classification, "classification"),
        )
        object.__setattr__(
            self,
            "scope_decision_making",
            _require_str(self.scope_decision_making, "scope_decision_making", allow_empty=True),
        )
        object.__setattr__(
            self,
            "core_competencies",
            _require_str(self.core_competencies, "core_competencies", allow_empty=True),
        )
        object.__setattr__(
            self,
            "level_expectations",
            _require_str(self.level_expectations, "level_expectations", allow_empty=True),
        )
        object.__setattr__(self, "progression", _require_str(self.progression, "progression", allow_empty=True))
        object.__setattr__(
            self,
            "evidence_note",
            _require_str(self.evidence_note, "evidence_note", allow_empty=True),
        )
        parse_fit_status(self.classification, "classification")

    def section_value(self, section_id: str) -> Any:
        if section_id not in PROFILE_SECTION_IDS:
            raise KeyError(section_id)
        if section_id == "title":
            return self.display_title
        if section_id == "family":
            return self.family_name or self.family_id
        if section_id == "track":
            return self.track_name or self.track_id
        if section_id == "level":
            return self.level_label or self.level_id
        if section_id == "purpose":
            return self.summary
        if section_id == "responsibilities":
            return list(self.responsibilities)
        if section_id == "scope_decision_making":
            return self.scope_decision_making
        if section_id == "core_competencies":
            return self.core_competencies
        if section_id == "level_expectations":
            return self.level_expectations
        if section_id == "progression":
            return self.progression
        if section_id == "evidence_note":
            return self.evidence_note
        return self.classification

    def with_section(self, section_id: str, value: Any) -> RoleProfile:
        from dataclasses import replace

        if section_id == "title":
            return replace(self, display_title=_require_str(value, "title"))
        if section_id == "family":
            return replace(self, family_name=_require_str(value, "family"))
        if section_id == "track":
            return replace(self, track_name=_require_str(value, "track"))
        if section_id == "level":
            return replace(self, level_label=_require_str(value, "level"))
        if section_id == "purpose":
            return replace(self, summary=_require_str(value, "purpose"))
        if section_id == "responsibilities":
            if isinstance(value, str):
                items = [line.strip() for line in value.split("\n") if line.strip()]
            else:
                items = list(value)
            return replace(self, responsibilities=_require_str_list(items, "responsibilities"))
        if section_id == "scope_decision_making":
            return replace(self, scope_decision_making=_require_str(value, "scope_decision_making"))
        if section_id == "core_competencies":
            return replace(self, core_competencies=_require_str(value, "core_competencies"))
        if section_id == "level_expectations":
            return replace(self, level_expectations=_require_str(value, "level_expectations"))
        if section_id == "progression":
            return replace(self, progression=_require_str(value, "progression"))
        if section_id == "evidence_note":
            return replace(self, evidence_note=_require_str(value, "evidence_note"))
        if section_id == "classification":
            return replace(self, classification=_require_str(value, "classification"))
        raise KeyError(section_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role_id": self.role_id,
            "family_id": self.family_id,
            "track_id": self.track_id,
            "level_id": self.level_id,
            "display_title": self.display_title,
            "summary": self.summary,
            "responsibilities": list(self.responsibilities),
            "competency_ids": list(self.competency_ids),
            "family_name": self.family_name,
            "track_name": self.track_name,
            "level_label": self.level_label,
            "classification": self.classification,
            "scope_decision_making": self.scope_decision_making,
            "core_competencies": self.core_competencies,
            "level_expectations": self.level_expectations,
            "progression": self.progression,
            "evidence_note": self.evidence_note,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RoleProfile:
        payload = _require_mapping(data, "role_profile")
        return cls(
            id=payload.get("id"),
            role_id=payload.get("role_id"),
            family_id=payload.get("family_id"),
            track_id=payload.get("track_id"),
            level_id=payload.get("level_id"),
            display_title=payload.get("display_title"),
            summary=payload.get("summary"),
            responsibilities=payload.get("responsibilities"),
            competency_ids=payload.get("competency_ids") or [],
            family_name=payload.get("family_name") or "",
            track_name=payload.get("track_name") or "",
            level_label=payload.get("level_label") or "",
            classification=payload.get("classification") or "strong_fit",
            scope_decision_making=payload.get("scope_decision_making") or "",
            core_competencies=payload.get("core_competencies") or "",
            level_expectations=payload.get("level_expectations") or "",
            progression=payload.get("progression") or "",
            evidence_note=payload.get("evidence_note") or "",
        )


@dataclass(frozen=True)
class DependencyEdge:
    """Directed dependency from canonical architecture content to a profile."""

    id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    target_section: str
    notes: str = ""
    source_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "source_type", _require_str(self.source_type, "source_type"))
        object.__setattr__(self, "source_id", _require_str(self.source_id, "source_id"))
        object.__setattr__(self, "target_type", _require_str(self.target_type, "target_type"))
        object.__setattr__(self, "target_id", _require_str(self.target_id, "target_id"))
        object.__setattr__(
            self,
            "target_section",
            _require_str(self.target_section, "target_section"),
        )
        object.__setattr__(self, "notes", _require_str(self.notes, "notes", allow_empty=True))
        if (
            not isinstance(self.source_version, int)
            or isinstance(self.source_version, bool)
            or self.source_version < 1
        ):
            raise ValueError("source_version must be an integer >= 1")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_type": self.source_type,
            "source_id": self.source_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_section": self.target_section,
            "notes": self.notes,
            "source_version": self.source_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DependencyEdge:
        payload = _require_mapping(data, "dependency_edge")
        version = payload.get("source_version", 1)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("source_version must be an integer >= 1")
        return cls(
            id=payload.get("id"),
            source_type=payload.get("source_type"),
            source_id=payload.get("source_id"),
            target_type=payload.get("target_type"),
            target_id=payload.get("target_id"),
            target_section=payload.get("target_section"),
            notes=payload.get("notes") or "",
            source_version=version,
        )


SERIALIZABLE_MODELS = (
    SourceReference,
    RoleEvidence,
    JobFamily,
    CareerTrack,
    LevelDefinition,
    Competency,
    MisfitReason,
    RoleAssessment,
    RoleProfile,
    DependencyEdge,
)


def round_trip(model: Any) -> Any:
    """Serialize a domain model to a dict and rebuild the same type."""
    if not hasattr(model, "to_dict") or not hasattr(model.__class__, "from_dict"):
        raise TypeError(f"{type(model).__name__} is not a serializable domain model")
    return model.__class__.from_dict(model.to_dict())
