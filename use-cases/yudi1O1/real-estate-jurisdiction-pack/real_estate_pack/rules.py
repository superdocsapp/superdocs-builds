"""Jurisdiction rule loading: disclosures, lease clauses, and numeric limits.

The task card's bar is that jurisdiction-specific disclosures are *correct and
dated*. "Dated" is the half that is easy to fake and easy to check, so it is
enforced structurally here rather than promised in prose:

* Every rule **must** carry a citation with an `authority`, a `source_url`, a
  `verified_on` date and a `review_by` date. A rule missing any of them fails to
  load — there is no way to add an uncited disclosure to this pack.
* `review_by` is a real expiry. Once it passes, the rule is **stale** and
  `validate.py` blocks the draft. Landlord-tenant law moves; a disclosure that
  was right in 2024 and is wrong now is worse than a missing one, because it
  looks authoritative.

Rules come in three kinds because a jurisdiction difference is not always a
document to hand over:

* ``disclosure`` — a notice that goes in the packet, often with statutorily
  mandated wording.
* ``lease_clause`` — a term that must appear in the lease itself.
* ``limit`` — an arithmetic ceiling (a security deposit cap), checked in Python
  against the numbers on the record. This is what makes "these jurisdictions
  differ meaningfully" provable rather than asserted: the same $4,000 deposit is
  lawful in Texas and unlawful in California.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Optional

import yaml

from .conditions import Evaluation, evaluate, referenced_fields
from .models import safe_slug

VALID_KINDS = frozenset({"disclosure", "lease_clause", "limit"})


class RuleFileError(ValueError):
    """A jurisdiction file that cannot be trusted. Always fatal at load time —
    silently skipping a malformed rule would silently drop a legal requirement."""


@dataclass(frozen=True)
class Citation:
    """Where a rule comes from and when someone last checked."""

    authority: str  # e.g. "Cal. Civ. Code § 1950.5(c)"
    source_url: str
    verified_on: date
    review_by: date
    note: str = ""

    def is_stale(self, today: date) -> bool:
        return today > self.review_by

    def render(self) -> str:
        return f"{self.authority} (verified {self.verified_on.isoformat()}, review by {self.review_by.isoformat()})"


@dataclass
class Rule:
    id: str
    kind: str
    title: str
    summary: str
    citation: Citation
    jurisdiction_code: str = ""
    jurisdiction_name: str = ""
    applies_when: Optional[dict] = None
    requires_facts: tuple[str, ...] = ()
    """Facts that must be ANSWERED once this rule applies, as distinct from facts
    that decide *whether* it applies.

    The distinction is load-bearing. Texas's flooding notice and New York's
    sprinkler notice are mandatory in every residential lease and must be
    answered in both directions — a "no" is a disclosure, not an exemption. An
    earlier version of this pack expressed that by making applicability depend on
    `is_set`, which inverted the safety property: leaving the question blank
    silently removed a mandatory disclosure and the lease looked complete. Now
    the rule always applies and the unanswered fact blocks instead."""
    preamble: str = ""
    """Non-statutory scaffolding rendered ABOVE the body: headings, and the
    fill-in fields a landlord completes.

    This exists so `verbatim_statutory` can stay honest. Florida's deposit notice
    prescribes two paragraphs word-for-word, but the depository name and account
    details around them are ordinary blanks. Marking the whole thing verbatim
    would overclaim — and would tell the model not to reformat a heading that it
    is perfectly free to reformat."""
    body: str = ""
    """The text that goes into the document. Where a statute mandates exact
    wording this is that wording verbatim — see `verbatim_statutory`."""
    verbatim_statutory: bool = False
    """True when the statute prescribes the words of `body` themselves, so
    paraphrasing is non-compliant. The AI is instructed never to reword these,
    and `check_consistency` proves the opening survived rendering intact."""
    tenant_acknowledgement: bool = False
    delivery: str = "with the lease"
    limit_spec: Optional[dict] = None
    notes: str = ""

    def evaluate(self, req) -> Evaluation:
        return evaluate(self.applies_when, req)

    def required_facts(self) -> list[str]:
        """Every fact this rule could need — for deciding applicability, and for
        completing the notice once it applies."""
        return list(dict.fromkeys(referenced_fields(self.applies_when) + list(self.requires_facts)))


@dataclass
class Jurisdiction:
    code: str  # "US-CA"
    name: str  # "California"
    rules: list[Rule] = field(default_factory=list)
    notes: str = ""

    def disclosures(self) -> list[Rule]:
        return [r for r in self.rules if r.kind == "disclosure"]

    def lease_clauses(self) -> list[Rule]:
        return [r for r in self.rules if r.kind == "lease_clause"]

    def limits(self) -> list[Rule]:
        return [r for r in self.rules if r.kind == "limit"]


def _require(mapping: dict, key: str, where: str) -> Any:
    if key not in mapping or mapping[key] in (None, ""):
        raise RuleFileError(f"{where}: missing required field '{key}'.")
    return mapping[key]


def _parse_date(value: Any, where: str, key: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except (ValueError, AttributeError) as e:
        raise RuleFileError(f"{where}: '{key}' must be an ISO date (YYYY-MM-DD), got {value!r}.") from e


def _parse_citation(raw: Any, where: str) -> Citation:
    if not isinstance(raw, dict):
        raise RuleFileError(f"{where}: 'citation' must be a mapping with authority/source_url/verified_on/review_by.")
    verified_on = _parse_date(_require(raw, "verified_on", where), where, "verified_on")
    review_by = _parse_date(_require(raw, "review_by", where), where, "review_by")
    if review_by < verified_on:
        raise RuleFileError(f"{where}: 'review_by' ({review_by}) is before 'verified_on' ({verified_on}).")
    return Citation(
        authority=str(_require(raw, "authority", where)),
        source_url=str(_require(raw, "source_url", where)),
        verified_on=verified_on,
        review_by=review_by,
        note=str(raw.get("note", "")),
    )


def _parse_rule(raw: Any, where: str, code: str, name: str) -> Rule:
    if not isinstance(raw, dict):
        raise RuleFileError(f"{where}: each rule must be a mapping.")
    rule_id = str(_require(raw, "id", where))
    where = f"{where} rule '{rule_id}'"
    kind = str(_require(raw, "kind", where))
    if kind not in VALID_KINDS:
        raise RuleFileError(f"{where}: kind '{kind}' is not one of {sorted(VALID_KINDS)}.")

    limit_spec = raw.get("limit")
    if kind == "limit":
        if not isinstance(limit_spec, dict):
            raise RuleFileError(f"{where}: kind 'limit' requires a 'limit' mapping.")
        _require(limit_spec, "field", where)
    elif kind == "disclosure" and not str(raw.get("body", "")).strip():
        raise RuleFileError(f"{where}: a disclosure needs a 'body' — the text handed to the tenant.")

    requires_facts = raw.get("requires_facts") or []
    if not isinstance(requires_facts, list) or any(not isinstance(f, str) for f in requires_facts):
        raise RuleFileError(f"{where}: 'requires_facts' must be a list of fact names.")

    return Rule(
        id=rule_id,
        kind=kind,
        title=str(_require(raw, "title", where)),
        summary=str(raw.get("summary", "")),
        citation=_parse_citation(_require(raw, "citation", where), where),
        jurisdiction_code=code,
        jurisdiction_name=name,
        applies_when=raw.get("applies_when"),
        requires_facts=tuple(requires_facts),
        preamble=str(raw.get("preamble", "")).strip(),
        body=str(raw.get("body", "")).strip(),
        verbatim_statutory=bool(raw.get("verbatim_statutory", False)),
        tenant_acknowledgement=bool(raw.get("tenant_acknowledgement", False)),
        delivery=str(raw.get("delivery", "with the lease")),
        limit_spec=limit_spec if kind == "limit" else None,
        notes=str(raw.get("notes", "")),
    )


def load_jurisdiction_file(path: str | Path) -> Jurisdiction:
    path = Path(path)
    where = path.name
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except FileNotFoundError as e:
        raise RuleFileError(f"No jurisdiction file at {path}.") from e
    except yaml.YAMLError as e:
        raise RuleFileError(f"{where}: not valid YAML — {e}") from e

    if not isinstance(raw, dict):
        raise RuleFileError(f"{where}: top level must be a mapping.")

    code = str(_require(raw, "code", where))
    name = str(_require(raw, "name", where))
    rules_raw = raw.get("rules") or []
    if not isinstance(rules_raw, list):
        raise RuleFileError(f"{where}: 'rules' must be a list.")

    rules = [_parse_rule(r, where, code, name) for r in rules_raw]

    seen: set[str] = set()
    for rule in rules:
        if rule.id in seen:
            raise RuleFileError(f"{where}: duplicate rule id '{rule.id}'.")
        seen.add(rule.id)

    return Jurisdiction(code=code, name=name, rules=rules, notes=str(raw.get("notes", "")))


DEFAULT_RULES_DIR = Path(__file__).resolve().parent.parent / "jurisdictions"

#: Rules that apply everywhere in the United States, layered under every state.
FEDERAL_CODE = "US-FED"


#: A jurisdiction code is a plain identifier like `US-CA`. Nothing else is a code.
_CODE_SHAPE = re.compile(r"^[A-Za-z0-9_-]+$")


def _file_for(code: str, rules_dir: Path) -> Path:
    """Map a jurisdiction code to its rule file.

    The code arrives from a hand-written YAML record or from `--jurisdiction`, so
    it is untrusted input rather than a label: left raw, `../../../etc/passwd`
    resolves outside the rules directory.

    The shape is checked *before* any cleaning, deliberately. Silently
    sanitising `../us_ca` into `us_ca` would load California for a malformed
    code — safe, but it would quietly do something the user did not ask for,
    which is the behaviour this whole build refuses everywhere else. Naming the
    bad code is the consistent answer. The containment check below then stands as
    belt and braces, because a path guard resting only on string validation is
    one clever input away from being wrong.
    """
    if not _CODE_SHAPE.match(code or ""):
        raise RuleFileError(
            f"Jurisdiction code {code!r} is not a plain code such as US-CA. "
            f"Letters, digits, hyphens and underscores only."
        )
    candidate = (rules_dir / f"{safe_slug(code.lower().replace('-', '_'), 'unknown')}.yaml").resolve()
    if rules_dir.resolve() not in candidate.parents:
        raise RuleFileError(f"Jurisdiction code {code!r} does not resolve inside {rules_dir}.")
    return candidate


def available_jurisdictions(rules_dir: str | Path = DEFAULT_RULES_DIR) -> list[str]:
    rules_dir = Path(rules_dir)
    if not rules_dir.is_dir():
        return []
    codes = []
    for path in sorted(rules_dir.glob("*.yaml")):
        try:
            codes.append(load_jurisdiction_file(path).code)
        except RuleFileError:
            continue
    return codes


def load_ruleset(code: str, rules_dir: str | Path = DEFAULT_RULES_DIR) -> Jurisdiction:
    """Load one jurisdiction with the federal layer merged underneath it.

    Federal rules come first so they are numbered first in the packet, which
    matches how these packets are conventionally ordered and keeps the lead-paint
    disclosure — the one with real teeth — at the top rather than buried.
    """
    rules_dir = Path(rules_dir)
    path = _file_for(code, rules_dir)
    if not path.exists():
        known = available_jurisdictions(rules_dir)
        raise RuleFileError(
            f"No rules for jurisdiction '{code}'. Known: {', '.join(known) if known else '(none found)'}. "
            f"Fix: add {path.name} to {rules_dir}, or pass one of the codes above."
        )
    jurisdiction = load_jurisdiction_file(path)

    if code.upper() != FEDERAL_CODE:
        federal_path = _file_for(FEDERAL_CODE, rules_dir)
        if federal_path.exists():
            federal = load_jurisdiction_file(federal_path)
            merged = list(federal.rules) + list(jurisdiction.rules)
            clashes = {r.id for r in federal.rules} & {r.id for r in jurisdiction.rules}
            if clashes:
                raise RuleFileError(
                    f"Rule id(s) {sorted(clashes)} defined in both {federal_path.name} and {path.name}. "
                    f"Fix: prefix state rules with the state code so they cannot collide with federal ones."
                )
            jurisdiction = Jurisdiction(
                code=jurisdiction.code, name=jurisdiction.name, rules=merged, notes=jurisdiction.notes
            )
    return jurisdiction


def stale_rules(jurisdiction: Jurisdiction, today: date) -> list[Rule]:
    return [r for r in jurisdiction.rules if r.citation.is_stale(today)]
