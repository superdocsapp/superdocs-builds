"""Load synthetic corpora without any SuperDocs or model-provider calls."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

from job_architecture.models import FitStatus, parse_fit_status, _require_mapping, _require_str, _require_str_list

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = PROJECT_ROOT / "fixtures"

REQUIRED_SECTION_HEADINGS = (
    "team",
    "role purpose",
    "responsibilities",
    "scope and autonomy",
    "leadership and management",
    "stakeholders",
    "requirements",
)

# Source JDs must not contain test-oracle hints. These patterns are matched
# case-insensitively against raw markdown.
FORBIDDEN_SOURCE_HINT_PATTERNS = (
    r"expected\s+family",
    r"expected\s+level",
    r"expected\s+track",
    r"expected_family",
    r"expected_level",
    r"expected_track",
    r"fit_status",
    r"strong_fit",
    r"\bmisfit\b",
    r"\bprovisional\b",
    r"job\s+family",
    r"career\s+track",
    r"expected\s+classification",
)

_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_FORBIDDEN_RE = re.compile(
    "|".join(f"(?:{pattern})" for pattern in FORBIDDEN_SOURCE_HINT_PATTERNS),
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CorpusRole:
    id: str
    file: str
    title: str
    team: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _require_str(self.id, "id"))
        object.__setattr__(self, "file", _require_str(self.file, "file"))
        object.__setattr__(self, "title", _require_str(self.title, "title"))
        object.__setattr__(self, "team", _require_str(self.team, "team"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CorpusRole:
        payload = _require_mapping(data, "corpus_role")
        return cls(
            id=payload.get("id"),
            file=payload.get("file"),
            title=payload.get("title"),
            team=payload.get("team"),
        )


@dataclass(frozen=True)
class CorpusManifest:
    corpus_id: str
    organization: str
    description: str
    roles: tuple[CorpusRole, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_id", _require_str(self.corpus_id, "corpus_id"))
        object.__setattr__(self, "organization", _require_str(self.organization, "organization"))
        object.__setattr__(self, "description", _require_str(self.description, "description"))
        if not self.roles:
            raise ValueError("roles must not be empty")
        ids = [role.id for role in self.roles]
        if len(ids) != len(set(ids)):
            raise ValueError("role ids in the manifest must be unique")

    def role_ids(self) -> list[str]:
        return [role.id for role in self.roles]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> CorpusManifest:
        payload = _require_mapping(data, "manifest")
        raw_roles = payload.get("roles")
        if not isinstance(raw_roles, list):
            raise ValueError("roles must be a list")
        roles = tuple(CorpusRole.from_dict(item) for item in raw_roles)
        return cls(
            corpus_id=payload.get("corpus_id"),
            organization=payload.get("organization"),
            description=payload.get("description"),
            roles=roles,
        )


@dataclass(frozen=True)
class ExpectedRole:
    role_id: str
    fit_status: FitStatus
    proposed_family: str | None = None
    proposed_track: str | None = None
    proposed_level: str | None = None
    notes: str = ""
    adversarial_case: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "role_id", _require_str(self.role_id, "role_id"))
        object.__setattr__(self, "fit_status", parse_fit_status(self.fit_status))
        proposed_family = self.proposed_family
        proposed_track = self.proposed_track
        proposed_level = self.proposed_level
        object.__setattr__(
            self,
            "proposed_family",
            None if proposed_family is None else _require_str(proposed_family, "proposed_family"),
        )
        object.__setattr__(
            self,
            "proposed_track",
            None if proposed_track is None else _require_str(proposed_track, "proposed_track"),
        )
        object.__setattr__(
            self,
            "proposed_level",
            None if proposed_level is None else _require_str(proposed_level, "proposed_level"),
        )
        object.__setattr__(self, "notes", _require_str(self.notes, "notes", allow_empty=True))
        adversarial = self.adversarial_case
        object.__setattr__(
            self,
            "adversarial_case",
            None if adversarial is None else _require_str(adversarial, "adversarial_case"),
        )
        if self.fit_status is FitStatus.STRONG_FIT and self.proposed_family is None:
            raise ValueError(f"{self.role_id}: strong_fit requires proposed_family")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExpectedRole:
        payload = _require_mapping(data, "expected_role")
        return cls(
            role_id=payload.get("role_id"),
            fit_status=payload.get("fit_status"),
            proposed_family=payload.get("proposed_family"),
            proposed_track=payload.get("proposed_track"),
            proposed_level=payload.get("proposed_level"),
            notes=payload.get("notes") or "",
            adversarial_case=payload.get("adversarial_case"),
        )


@dataclass(frozen=True)
class ExpectedCorpus:
    corpus_id: str
    organization: str
    assessments: tuple[ExpectedRole, ...]
    adversarial_cases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "corpus_id", _require_str(self.corpus_id, "corpus_id"))
        object.__setattr__(self, "organization", _require_str(self.organization, "organization"))
        if not self.assessments:
            raise ValueError("assessments must not be empty")
        ids = [item.role_id for item in self.assessments]
        if len(ids) != len(set(ids)):
            raise ValueError("role_id values in expected.json must be unique")
        object.__setattr__(
            self,
            "adversarial_cases",
            tuple(_require_str_list(list(self.adversarial_cases), "adversarial_cases")),
        )

    def by_role_id(self) -> dict[str, ExpectedRole]:
        return {item.role_id: item for item in self.assessments}

    def adversarial_roles(self) -> list[ExpectedRole]:
        return [item for item in self.assessments if item.adversarial_case]

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ExpectedCorpus:
        payload = _require_mapping(data, "expected")
        raw_assessments = payload.get("assessments")
        if not isinstance(raw_assessments, list):
            raise ValueError("assessments must be a list")
        assessments = tuple(ExpectedRole.from_dict(item) for item in raw_assessments)
        return cls(
            corpus_id=payload.get("corpus_id"),
            organization=payload.get("organization"),
            assessments=assessments,
            adversarial_cases=payload.get("adversarial_cases") or [],
        )


@dataclass(frozen=True)
class ParsedJobDescription:
    role_id: str
    path: Path
    title: str
    raw_markdown: str
    sections: dict[str, str] = field(default_factory=dict)

    def section(self, heading: str) -> str:
        return self.sections[heading.lower()]


@dataclass(frozen=True)
class LoadedCorpus:
    directory: Path
    manifest: CorpusManifest
    expected: ExpectedCorpus
    job_descriptions: tuple[ParsedJobDescription, ...]

    def job_description(self, role_id: str) -> ParsedJobDescription:
        for item in self.job_descriptions:
            if item.role_id == role_id:
                return item
        raise KeyError(role_id)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def parse_markdown_sections(markdown: str) -> tuple[str, dict[str, str]]:
    matches = list(_HEADING_RE.finditer(markdown))
    if not matches or not matches[0].group(0).startswith("# "):
        raise ValueError("job description must start with a level-1 title heading")
    title = matches[0].group(1).strip()
    sections: dict[str, str] = {}
    for index, match in enumerate(matches[1:], start=1):
        heading = match.group(1).strip().lower()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if heading in sections:
            raise ValueError(f"duplicate section heading: {heading}")
        sections[heading] = body
    return title, sections


def find_source_classification_hints(markdown: str) -> list[str]:
    return [match.group(0) for match in _FORBIDDEN_RE.finditer(markdown)]


def parse_job_description(path: Path, role_id: str) -> ParsedJobDescription:
    raw = path.read_text(encoding="utf-8")
    title, sections = parse_markdown_sections(raw)
    missing = [heading for heading in REQUIRED_SECTION_HEADINGS if heading not in sections]
    if missing:
        raise ValueError(f"{path.name}: missing required sections: {', '.join(missing)}")
    empty = [heading for heading in REQUIRED_SECTION_HEADINGS if not sections[heading].strip()]
    if empty:
        raise ValueError(f"{path.name}: empty required sections: {', '.join(empty)}")
    hints = find_source_classification_hints(raw)
    if hints:
        raise ValueError(
            f"{path.name}: source job description contains classification hints: {hints}"
        )
    return ParsedJobDescription(
        role_id=role_id,
        path=path,
        title=title,
        raw_markdown=raw,
        sections=sections,
    )


def load_corpus(corpus_id: str, *, fixtures_root: Path | None = None) -> LoadedCorpus:
    directory = (fixtures_root or FIXTURES_ROOT) / corpus_id
    if not directory.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {directory}")

    manifest = CorpusManifest.from_dict(load_json(directory / "manifest.json"))
    expected = ExpectedCorpus.from_dict(load_json(directory / "expected.json"))
    if manifest.corpus_id != corpus_id:
        raise ValueError(
            f"manifest corpus_id {manifest.corpus_id!r} does not match directory {corpus_id!r}"
        )
    if expected.corpus_id != corpus_id:
        raise ValueError(
            f"expected corpus_id {expected.corpus_id!r} does not match directory {corpus_id!r}"
        )
    if manifest.organization != expected.organization:
        raise ValueError("manifest and expected organization values must match")

    manifest_ids = set(manifest.role_ids())
    expected_ids = set(expected.by_role_id())
    if manifest_ids != expected_ids:
        raise ValueError(
            "manifest and expected role ids differ: "
            f"only_in_manifest={sorted(manifest_ids - expected_ids)} "
            f"only_in_expected={sorted(expected_ids - manifest_ids)}"
        )

    job_descriptions: list[ParsedJobDescription] = []
    seen_files: set[str] = set()
    for role in manifest.roles:
        if role.file in seen_files:
            raise ValueError(f"duplicate file in manifest: {role.file}")
        seen_files.add(role.file)
        path = directory / role.file
        if not path.is_file():
            raise FileNotFoundError(f"missing job description: {path}")
        parsed = parse_job_description(path, role.id)
        if parsed.title != role.title:
            raise ValueError(
                f"{role.file}: markdown title {parsed.title!r} does not match manifest title {role.title!r}"
            )
        job_descriptions.append(parsed)

    extra_markdown = sorted(
        path.name
        for path in directory.glob("*.md")
        if path.name not in seen_files
    )
    if extra_markdown:
        raise ValueError(f"markdown files not listed in manifest: {extra_markdown}")

    return LoadedCorpus(
        directory=directory,
        manifest=manifest,
        expected=expected,
        job_descriptions=tuple(job_descriptions),
    )


def iter_corpora(*, fixtures_root: Path | None = None) -> Iterator[LoadedCorpus]:
    root = fixtures_root or FIXTURES_ROOT
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        if (child / "manifest.json").exists():
            yield load_corpus(child.name, fixtures_root=root)


def list_corpus_ids(*, fixtures_root: Path | None = None) -> list[str]:
    return [corpus.manifest.corpus_id for corpus in iter_corpora(fixtures_root=fixtures_root)]
