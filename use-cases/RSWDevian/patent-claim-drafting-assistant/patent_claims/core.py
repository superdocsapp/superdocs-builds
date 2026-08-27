from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any


class ClaimValidationError(ValueError):
    """Raised when a claim set or amendment cannot be applied safely."""


_REFERENCE_RE = re.compile(r"\bclaims?\s+((?:\d+(?:\s*-\s*\d+)?(?:\s*(?:,|and|through)\s*)?)+)", re.IGNORECASE)
_INT_OR_RANGE_RE = re.compile(r"\d+(?:\s*-\s*\d+)?")


def extract_references(text: str) -> list[int]:
    """Deterministically find every 'claim N' style reference in claim text.

    No model call: a missed or invented reference here would silently break the
    dependency graph the rest of the system relies on, so this stays regex-exact.
    """
    numbers: list[int] = []
    for match in _REFERENCE_RE.finditer(text):
        for token in _INT_OR_RANGE_RE.findall(match.group(1)):
            if "-" in token:
                start_str, end_str = (part.strip() for part in token.split("-", 1))
                start, end = int(start_str), int(end_str)
                numbers.extend(range(start, end + 1) if start <= end else range(end, start + 1))
            else:
                numbers.append(int(token))
    seen: set[int] = set()
    ordered: list[int] = []
    for number in numbers:
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    return ordered


def _renumber_references(text: str, mapping: dict[int, int]) -> str:
    def replace_span(match: re.Match[str]) -> str:
        span = match.group(0)
        head = span[: len(span) - len(match.group(1))]
        body = span[len(head) :]

        def replace_number(number_match: re.Match[str]) -> str:
            value = int(number_match.group(0))
            return str(mapping.get(value, value))

        return head + re.sub(r"\d+", replace_number, body)

    return _REFERENCE_RE.sub(replace_span, text)


@dataclass(frozen=True)
class Claim:
    number: int
    text: str
    depends_on: tuple[int, ...] = field(default_factory=tuple)

    @property
    def kind(self) -> str:
        return "dependent" if self.depends_on else "independent"

    def as_dict(self) -> dict[str, Any]:
        return {"number": self.number, "text": self.text, "kind": self.kind, "depends_on": list(self.depends_on)}


@dataclass(frozen=True)
class ClaimSet:
    claims: tuple[Claim, ...]

    def by_number(self) -> dict[int, Claim]:
        return {claim.number: claim for claim in self.claims}

    def dependents_of(self, claim_number: int) -> dict[int, list[int]]:
        """Direct dependents: claim_number -> [claims that reference it directly]."""
        direct: dict[int, list[int]] = {claim.number: [] for claim in self.claims}
        for claim in self.claims:
            for target in claim.depends_on:
                direct.setdefault(target, []).append(claim.number)
        return direct

    def transitive_dependents(self, claim_number: int) -> list[int]:
        direct = self.dependents_of(claim_number)
        seen: set[int] = set()
        queue = list(direct.get(claim_number, []))
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            queue.extend(direct.get(current, []))
        return sorted(seen)

    def as_list(self) -> list[dict[str, Any]]:
        return [claim.as_dict() for claim in self.claims]


def build_claim_set(raw_claims: list[dict[str, Any]]) -> ClaimSet:
    if not isinstance(raw_claims, list) or not raw_claims:
        raise ClaimValidationError("claims must be a non-empty array")
    parsed: list[Claim] = []
    numbers: set[int] = set()
    for index, raw in enumerate(raw_claims):
        pointer = f"claims[{index}]"
        if not isinstance(raw, dict):
            raise ClaimValidationError(f"{pointer} must be an object")
        if "number" not in raw or not isinstance(raw["number"], int) or raw["number"] < 1:
            raise ClaimValidationError(f"{pointer}.number must be a positive integer")
        if "text" not in raw or not isinstance(raw["text"], str) or not raw["text"].strip():
            raise ClaimValidationError(f"{pointer}.text must be a non-empty string")
        number = raw["number"]
        if number in numbers:
            raise ClaimValidationError(f"duplicate claim number: {number}")
        numbers.add(number)
        parsed.append(Claim(number=number, text=raw["text"], depends_on=tuple(extract_references(raw["text"]))))
    parsed.sort(key=lambda claim: claim.number)
    if [claim.number for claim in parsed] != list(range(1, len(parsed) + 1)):
        raise ClaimValidationError("claim numbers must be contiguous starting at 1")
    known = numbers
    for claim in parsed:
        dangling = [target for target in claim.depends_on if target not in known]
        if dangling:
            raise ClaimValidationError(f"claim {claim.number} references unknown claim(s) {dangling}")
        if claim.number in claim.depends_on:
            raise ClaimValidationError(f"claim {claim.number} cannot depend on itself")
    return ClaimSet(claims=tuple(parsed))


def amend_claim(claim_set: ClaimSet, claim_number: int, new_text: str) -> tuple[ClaimSet, list[int]]:
    """Return (new claim set, flagged transitive dependents) — the amendment is
    NOT applied to dependent claim text; those are surfaced for human review,
    matching the brief: 'flags or updates every dependent claim', never silent.
    """
    by_number = claim_set.by_number()
    if claim_number not in by_number:
        raise ClaimValidationError(f"claim {claim_number} does not exist")
    if not isinstance(new_text, str) or not new_text.strip():
        raise ClaimValidationError("new_text must be a non-empty string")
    flagged = claim_set.transitive_dependents(claim_number)
    raw = [
        {"number": claim.number, "text": new_text if claim.number == claim_number else claim.text}
        for claim in claim_set.claims
    ]
    return build_claim_set(raw), flagged


def delete_claim(claim_set: ClaimSet, claim_number: int) -> ClaimSet:
    """Remove a claim and renumber deterministically. Refuses when other claims
    depend on it: silently repointing a dependent claim at a different claim
    would change its legal scope, which is not this system's call to make.
    """
    by_number = claim_set.by_number()
    if claim_number not in by_number:
        raise ClaimValidationError(f"claim {claim_number} does not exist")
    dependents = claim_set.dependents_of(claim_number).get(claim_number, [])
    if dependents:
        raise ClaimValidationError(
            f"claim {claim_number} cannot be deleted: claim(s) {dependents} depend on it directly; "
            "amend or delete those first"
        )
    mapping = {}
    next_number = 1
    for claim in claim_set.claims:
        if claim.number == claim_number:
            continue
        mapping[claim.number] = next_number
        next_number += 1
    raw = [
        {"number": mapping[claim.number], "text": _renumber_references(claim.text, mapping)}
        for claim in claim_set.claims
        if claim.number != claim_number
    ]
    return build_claim_set(raw)


def diff_claim_sets(before: ClaimSet, after: ClaimSet) -> list[dict[str, Any]]:
    before_by = {claim.number: claim.text for claim in before.claims}
    after_by = {claim.number: claim.text for claim in after.claims}
    changes = []
    for number in sorted(set(before_by) | set(after_by)):
        if before_by.get(number) != after_by.get(number):
            changes.append({"number": number, "before": before_by.get(number), "after": after_by.get(number)})
    return changes


def claims_from_list(raw_claims: list[dict[str, Any]]) -> ClaimSet:
    """Reconstruct a ClaimSet from already-validated stored claim dicts (carries
    `depends_on` as-is instead of re-deriving it from text a second time).
    """
    return ClaimSet(claims=tuple(
        Claim(number=item["number"], text=item["text"], depends_on=tuple(item.get("depends_on", ())))
        for item in raw_claims
    ))


@dataclass
class Patent:
    patent_id: str
    title: str
    applicant: str
    revision: int
    status: str
    claims: ClaimSet
    revision_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patent_id": self.patent_id, "title": self.title, "applicant": self.applicant,
            "revision": self.revision, "status": self.status,
            "claims": self.claims.as_list(), "revision_history": deepcopy(self.revision_history),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Patent":
        """Reconstruct from a previously stored/validated `to_dict()` shape."""
        return cls(
            patent_id=value["patent_id"], title=value["title"], applicant=value["applicant"],
            revision=value["revision"], status=value["status"],
            claims=claims_from_list(value["claims"]), revision_history=list(value.get("revision_history", [])),
        )

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


def patent_from_payload(payload: dict[str, Any]) -> Patent:
    """Build a fresh Patent from newly drafted claims: `{"number": N, "text": str}`
    only. Dependencies are derived from claim text here, never trusted from the
    caller, matching `build_claim_set`.
    """
    data = dict(payload.get("patent", payload))
    if "patent_id" not in data or "title" not in data or "applicant" not in data:
        raise ClaimValidationError("patent requires patent_id, title, and applicant")
    return Patent(
        patent_id=data["patent_id"], title=data["title"], applicant=data["applicant"],
        revision=data.get("revision", 1), status=data.get("status", "review-ready"),
        claims=build_claim_set(data["claims"]), revision_history=list(data.get("revision_history", [])),
    )
