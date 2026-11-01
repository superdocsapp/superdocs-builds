"""The deal specification — the single source of truth for a whole document set.

Every document this build produces is a *projection* of the deal spec: the integration
charter, each workstream charter, the day-one checklists, the synergy tracker and the
communications pack all say things that trace back to a field here.

That is the load-bearing decision, and it is what makes the card's hardest requirement
achievable at all. "Master-to-workstream consistency holds after edits made on either
side" is impossible to guarantee between N documents that merely agreed when they were
written — each edit is a chance to drift, and there is no arbiter. With a spec in the
middle, consistency is a comparison against one artifact rather than N-squared
comparisons between documents, and an edit on either side is reconciled the same way.

The spec is YAML because a new deal, a new workstream, or a new synergy must be a data
change and never a code change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


class DealSpecError(ValueError):
    """The deal file is malformed.

    Raised at load time with the offending field named. A spec that is silently
    half-read produces a document set that is confidently wrong, which is far worse
    than refusing to start.
    """


@dataclass(frozen=True)
class Synergy:
    """A claimed saving or revenue gain, owned by exactly one workstream."""

    id: str
    description: str
    annual_value_usd: Decimal
    realisation_month: int
    owner: str  # workstream key

    @property
    def value_display(self) -> str:
        return f"${self.annual_value_usd:,.0f}"


@dataclass(frozen=True)
class Dependency:
    """Something a workstream needs, or provides, before work can proceed."""

    id: str
    description: str
    owner: str  # workstream key that OWNS delivery
    needed_by_month: int
    needed_by: list[str] = field(default_factory=list)  # workstream keys that consume it


@dataclass(frozen=True)
class DayOneItem:
    """A readiness item that must be true on day one.

    `depends_on` is what makes the day-one checklist deal-specific rather than generic:
    an item that relies on a dependency not delivered until month three is a real
    finding about *this* deal, not a template line.
    """

    id: str
    description: str
    owner: str
    depends_on: list[str] = field(default_factory=list)  # dependency ids
    status: str = "not_started"


@dataclass(frozen=True)
class Workstream:
    key: str
    name: str
    lead: str
    scope: str
    synergies: list[Synergy] = field(default_factory=list)
    dependencies: list[Dependency] = field(default_factory=list)
    day_one: list[DayOneItem] = field(default_factory=list)

    @property
    def synergy_total(self) -> Decimal:
        return sum((s.annual_value_usd for s in self.synergies), Decimal(0))


@dataclass(frozen=True)
class TargetProfile:
    headcount: int
    locations: list[str]
    systems: list[dict[str, str]]
    notes: str = ""


@dataclass(frozen=True)
class Deal:
    code_name: str
    acquirer: str
    target: str
    announced: date
    expected_close: date
    integration_horizon_months: int
    deal_value_usd: Decimal
    synergy_target_usd: Decimal
    rationale: str
    profile: TargetProfile
    workstreams: list[Workstream]

    # -- derived ---------------------------------------------------------------

    @property
    def all_synergies(self) -> list[Synergy]:
        return [s for w in self.workstreams for s in w.synergies]

    @property
    def all_dependencies(self) -> list[Dependency]:
        return [d for w in self.workstreams for d in w.dependencies]

    @property
    def all_day_one(self) -> list[DayOneItem]:
        return [i for w in self.workstreams for i in w.day_one]

    @property
    def claimed_synergy_total(self) -> Decimal:
        return sum((s.annual_value_usd for s in self.all_synergies), Decimal(0))

    def workstream(self, key: str) -> Workstream | None:
        return next((w for w in self.workstreams if w.key == key), None)

    def dependency(self, dependency_id: str) -> Dependency | None:
        return next((d for d in self.all_dependencies if d.id == dependency_id), None)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise DealSpecError(f"{where}: missing required field {key!r}")
    return mapping[key]


def _as_date(value: Any, where: str) -> date:
    if isinstance(value, date):
        return value
    raise DealSpecError(
        f"{where}: expected a date (YYYY-MM-DD), got {value!r}. "
        f"Quote it and it becomes a string, which is not the same thing."
    )


def _as_money(value: Any, where: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "").replace("$", ""))
    except Exception as exc:
        raise DealSpecError(f"{where}: {value!r} is not a number") from exc


def load_deal(path: Path) -> Deal:
    """Load and validate a deal spec.

    Validation is thorough and happens here rather than at use time, because the
    failure mode of a half-valid spec is a complete, plausible, wrong document set —
    and nobody reading a polished integration charter thinks to doubt the input file.
    """
    # A typo'd path and a malformed file are the two commonest first interactions with
    # any tool that takes one. Both used to surface as raw tracebacks, which tells the
    # user the tool is broken rather than that they mistyped something.
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise DealSpecError(f"no such deal file: {path}") from None
    except OSError as exc:
        raise DealSpecError(f"cannot read {path}: {exc.strerror or exc}") from None

    try:
        raw = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        # YAML errors carry the line and column; keep them, drop the traceback.
        where = getattr(exc, "problem_mark", None)
        location = f" at line {where.line + 1}, column {where.column + 1}" if where else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        raise DealSpecError(f"{path.name} is not valid YAML{location}: {problem}") from None

    if not isinstance(raw, dict):
        raise DealSpecError(
            f"{path.name}: expected a mapping at the top level, got "
            f"{type(raw).__name__}"
        )

    deal_block = _require(raw, "deal", path.name)
    profile_block = _require(raw, "target_profile", path.name)
    workstream_blocks = _require(raw, "workstreams", path.name)

    if not workstream_blocks:
        raise DealSpecError(f"{path.name}: a deal needs at least one workstream")

    profile = TargetProfile(
        headcount=int(_require(profile_block, "headcount", "target_profile")),
        locations=list(profile_block.get("locations") or []),
        systems=list(profile_block.get("systems") or []),
        notes=profile_block.get("notes", ""),
    )

    workstreams: list[Workstream] = []
    seen_keys: set[str] = set()

    for index, block in enumerate(workstream_blocks):
        where = f"{path.name} workstream #{index + 1}"
        key = _require(block, "key", where)

        if key in seen_keys:
            raise DealSpecError(f"{where}: duplicate workstream key {key!r}")
        seen_keys.add(key)

        synergies = [
            Synergy(
                id=_require(s, "id", f"{where} synergy"),
                description=_require(s, "description", f"{where} synergy"),
                annual_value_usd=_as_money(
                    _require(s, "annual_value_usd", f"{where} synergy"), f"{where} synergy"
                ),
                realisation_month=int(s.get("realisation_month", 12)),
                owner=key,
            )
            for s in (block.get("synergies") or [])
        ]

        dependencies = [
            Dependency(
                id=_require(d, "id", f"{where} dependency"),
                description=_require(d, "description", f"{where} dependency"),
                owner=key,
                needed_by_month=int(d.get("needed_by_month", 0)),
                needed_by=list(d.get("needed_by") or []),
            )
            for d in (block.get("dependencies") or [])
        ]

        day_one = [
            DayOneItem(
                id=_require(i, "id", f"{where} day_one"),
                description=_require(i, "description", f"{where} day_one"),
                owner=key,
                depends_on=list(i.get("depends_on") or []),
                status=i.get("status", "not_started"),
            )
            for i in (block.get("day_one") or [])
        ]

        workstreams.append(
            Workstream(
                key=key,
                name=_require(block, "name", where),
                lead=block.get("lead", "unassigned"),
                scope=block.get("scope", ""),
                synergies=synergies,
                dependencies=dependencies,
                day_one=day_one,
            )
        )

    deal = Deal(
        code_name=_require(deal_block, "code_name", "deal"),
        acquirer=_require(deal_block, "acquirer", "deal"),
        target=_require(deal_block, "target", "deal"),
        announced=_as_date(_require(deal_block, "announced", "deal"), "deal.announced"),
        expected_close=_as_date(
            _require(deal_block, "expected_close", "deal"), "deal.expected_close"
        ),
        integration_horizon_months=int(deal_block.get("integration_horizon_months", 12)),
        deal_value_usd=_as_money(_require(deal_block, "deal_value_usd", "deal"), "deal"),
        synergy_target_usd=_as_money(
            _require(deal_block, "synergy_target_usd", "deal"), "deal"
        ),
        rationale=deal_block.get("rationale", ""),
        profile=profile,
        workstreams=workstreams,
    )

    if deal.expected_close < deal.announced:
        raise DealSpecError(
            f"{path.name}: expected_close ({deal.expected_close}) is before "
            f"announced ({deal.announced})"
        )

    # Referential integrity, checked once at load. A day-one item pointing at a
    # dependency that does not exist would otherwise surface as a confidently generated
    # checklist entry with no basis, which is the kind of error nobody catches by reading.
    known_dependencies = {d.id for d in deal.all_dependencies}
    for item in deal.all_day_one:
        for needed in item.depends_on:
            if needed not in known_dependencies:
                raise DealSpecError(
                    f"{path.name}: day-one item {item.id!r} depends on {needed!r}, "
                    f"which no workstream declares"
                )

    known_workstreams = {w.key for w in deal.workstreams}
    for dependency in deal.all_dependencies:
        for consumer in dependency.needed_by:
            if consumer not in known_workstreams:
                raise DealSpecError(
                    f"{path.name}: dependency {dependency.id!r} is needed by "
                    f"{consumer!r}, which is not a workstream"
                )

    return deal
