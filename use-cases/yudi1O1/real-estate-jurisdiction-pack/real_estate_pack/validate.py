"""The blocking gate. Every pack passes through here before any network call.

Three things block a draft, and each exists because the failure it prevents is
silent rather than loud:

1. **An unanswered applicability question.** If nobody has said whether the
   building has a sprinkler system, New York's notice cannot be included *or*
   correctly omitted. Two-state logic would drop it and the lease would look
   fine. So an UNDETERMINED rule is a blocking finding naming the exact fact.

2. **A stale rule.** Every rule carries `review_by`. Past that date the rule is
   refused rather than used, because landlord-tenant law that was right last
   year and is wrong now produces a document that is confidently, invisibly
   non-compliant. `--allow-stale` proceeds, but every stale rule is then stamped
   UNVERIFIED in the compliance index — the override is recorded in the output,
   not just in the operator's memory.

3. **A deposit above the jurisdiction's cap.** Arithmetic, done in Python from
   the numbers on the record. This is the check that makes "these jurisdictions
   differ meaningfully" a fact rather than a claim: the same $4,000 deposit on
   $2,000 rent passes in Texas and Florida and blocks in California and New York.

Warnings never block. They are for things a coordinator should look at but which
are not defects — a pack with no disclosures at all, a term that ends before it
starts being blocking, but a single-day gap being merely odd.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .conditions import ConditionError
from .facts import FactView
from .models import UNSET, LeasePackRequest
from .rules import Jurisdiction, Rule


@dataclass
class Finding:
    severity: str  # "blocking" | "warning"
    location: str  # e.g. "rule ny_sprinkler_disclosure" or "tenancy.security_deposit"
    message: str


@dataclass
class RuleDecision:
    """What the engine concluded about one rule for one property."""

    rule: Rule
    applies: bool
    undetermined: bool = False
    missing_facts: tuple[str, ...] = ()
    stale: bool = False


@dataclass
class ValidationResult:
    findings: list[Finding] = field(default_factory=list)
    decisions: list[RuleDecision] = field(default_factory=list)

    @property
    def blocking(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocking"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok_to_draft(self) -> bool:
        return not self.blocking

    def applicable(self) -> list[Rule]:
        """Rules that fire for this property, in file order (federal first)."""
        return [d.rule for d in self.decisions if d.applies]

    def missing_facts(self) -> list[str]:
        names: list[str] = []
        for decision in self.decisions:
            names.extend(decision.missing_facts)
        return list(dict.fromkeys(names))


def _deposit_limit_findings(
    rule: Rule, req: LeasePackRequest, small_landlord_exception: bool, result: ValidationResult
) -> None:
    spec = rule.limit_spec or {}
    field_name = spec.get("field", "security_deposit")
    relative_to = spec.get("relative_to")
    max_multiple = spec.get("max_multiple")

    actual = getattr(req.tenancy, field_name, None)
    if actual is None:
        result.findings.append(
            Finding("blocking", f"tenancy.{field_name}", f"{field_name} was not supplied, so the "
                    f"{rule.jurisdiction_name} cap under {rule.citation.authority} cannot be checked.")
        )
        return

    if relative_to is None or max_multiple is None:
        return

    base = getattr(req.tenancy, relative_to, None)
    if base is None:
        result.findings.append(
            Finding("blocking", f"tenancy.{relative_to}",
                    f"{relative_to} was not supplied, so the {field_name} cap cannot be checked.")
        )
        return

    allowed_multiple = float(max_multiple)
    used_exception = False
    if small_landlord_exception and spec.get("exception_multiple") is not None:
        allowed_multiple = float(spec["exception_multiple"])
        used_exception = True

    ceiling = float(base) * allowed_multiple
    # Money compared with a cent of tolerance — a deposit set to exactly one
    # month's rent must not fail on binary float representation.
    if float(actual) > ceiling + 0.005:
        exception_hint = ""
        if not used_exception and spec.get("exception_note"):
            exception_hint = f" {spec['exception_note']}"
        result.findings.append(
            Finding(
                "blocking",
                f"tenancy.{field_name}",
                f"{field_name} of {float(actual):,.2f} exceeds the {rule.jurisdiction_name} ceiling of "
                f"{ceiling:,.2f} ({allowed_multiple:g} x {relative_to} of {float(base):,.2f}). "
                f"{spec.get('message', '').strip()} Authority: {rule.citation.render()}.{exception_hint}",
            )
        )
    elif used_exception:
        result.findings.append(
            Finding(
                "warning",
                f"tenancy.{field_name}",
                f"The {rule.jurisdiction_name} small-landlord exception was asserted, raising the ceiling to "
                f"{ceiling:,.2f}. This pack does not verify that the exception applies — confirm the landlord "
                f"actually meets its conditions. Authority: {rule.citation.render()}.",
            )
        )


def _validate_identity(req: LeasePackRequest, result: ValidationResult) -> None:
    if not req.landlord.name.strip():
        result.findings.append(Finding("blocking", "landlord.name", "Landlord name was not supplied."))
    if not req.tenants:
        result.findings.append(Finding("blocking", "tenants", "No tenant was supplied — a lease needs at least one."))
    for i, tenant in enumerate(req.tenants):
        if not tenant.name.strip():
            result.findings.append(Finding("blocking", f"tenants[{i}].name", "Tenant name is empty."))

    prop = req.property
    for attr, label in (("street_address", "street_address"), ("city", "city"), ("state", "state")):
        if not str(getattr(prop, attr, "")).strip():
            result.findings.append(Finding("blocking", f"property.{attr}", f"property.{label} was not supplied."))

    start, end = req.tenancy.parsed_start(), req.tenancy.parsed_end()
    if start is None:
        result.findings.append(
            Finding("blocking", "tenancy.start_date", f"start_date {req.tenancy.start_date!r} is not an ISO date (YYYY-MM-DD).")
        )
    if end is None:
        result.findings.append(
            Finding("blocking", "tenancy.end_date", f"end_date {req.tenancy.end_date!r} is not an ISO date (YYYY-MM-DD).")
        )
    if start is not None and end is not None and end < start:
        result.findings.append(
            Finding("blocking", "tenancy.end_date", f"end_date {end} is before start_date {start}.")
        )

    if req.tenancy.monthly_rent is None or float(req.tenancy.monthly_rent) <= 0:
        result.findings.append(Finding("blocking", "tenancy.monthly_rent", "monthly_rent must be a positive amount."))
    if req.tenancy.security_deposit is not None and float(req.tenancy.security_deposit) < 0:
        result.findings.append(Finding("blocking", "tenancy.security_deposit", "security_deposit cannot be negative."))


def validate_pack(
    req: LeasePackRequest,
    jurisdiction: Jurisdiction,
    today: Optional[date] = None,
    allow_stale: bool = False,
    small_landlord_exception: bool = False,
) -> ValidationResult:
    """Decide, for this property in this jurisdiction, which rules fire — and
    refuse to proceed if that question cannot be answered honestly."""
    today = today or date.today()
    result = ValidationResult()
    _validate_identity(req, result)

    view = FactView(req)

    for rule in jurisdiction.rules:
        try:
            evaluation = rule.evaluate(view)
        except ConditionError as e:
            # A malformed rule is a defect in the pack itself, not in the user's
            # input. Blocking is the only safe response: the alternative is
            # deciding, on the basis of a typo, that a legal requirement does
            # not apply.
            result.findings.append(
                Finding("blocking", f"rule {rule.id}",
                        f"This rule's applies_when condition is malformed and could not be evaluated: {e} "
                        f"Fix: correct {rule.jurisdiction_code} in jurisdictions/.")
            )
            result.decisions.append(RuleDecision(rule=rule, applies=False, undetermined=True))
            continue

        stale = rule.citation.is_stale(today)
        decision = RuleDecision(
            rule=rule,
            applies=evaluation.applies,
            undetermined=evaluation.undetermined,
            missing_facts=evaluation.missing_facts,
            stale=stale,
        )
        result.decisions.append(decision)

        if evaluation.undetermined:
            facts = ", ".join(evaluation.missing_facts)
            result.findings.append(
                Finding(
                    "blocking",
                    f"rule {rule.id}",
                    f"Cannot tell whether \"{rule.title}\" applies: {facts} "
                    f"{'was' if len(evaluation.missing_facts) == 1 else 'were'} not supplied. "
                    f"An unanswered question is never read as 'does not apply' — supply "
                    f"{'it' if len(evaluation.missing_facts) == 1 else 'them'} under disclosure_facts. "
                    f"Authority: {rule.citation.render()}.",
                )
            )
            continue

        if not evaluation.applies:
            continue

        # The rule applies. Anything it needs in order to be COMPLETE must now be
        # answered. This is separate from applicability on purpose: a mandatory
        # notice must not become optional just because nobody filled it in.
        unanswered = [name for name in rule.requires_facts if view.lookup_fact(name) is UNSET]
        if unanswered:
            decision.missing_facts = tuple(dict.fromkeys(decision.missing_facts + tuple(unanswered)))
            result.findings.append(
                Finding(
                    "blocking",
                    f"rule {rule.id}",
                    f"\"{rule.title}\" is required here and must be answered in both directions, but "
                    f"{', '.join(unanswered)} {'was' if len(unanswered) == 1 else 'were'} not supplied. "
                    f"A 'no' is a disclosure, not an exemption — supply "
                    f"{'it' if len(unanswered) == 1 else 'them'} under disclosure_facts. "
                    f"Authority: {rule.citation.render()}.",
                )
            )

        if stale:
            severity = "warning" if allow_stale else "blocking"
            prefix = (
                "PROCEEDING ANYWAY (--allow-stale): this rule will be marked UNVERIFIED in the compliance index. "
                if allow_stale
                else ""
            )
            result.findings.append(
                Finding(
                    severity,
                    f"rule {rule.id}",
                    f"{prefix}\"{rule.title}\" was last verified on {rule.citation.verified_on.isoformat()} "
                    f"and was due for review by {rule.citation.review_by.isoformat()}, which has passed "
                    f"(today is {today.isoformat()}). Re-verify against {rule.citation.source_url} and update "
                    f"verified_on/review_by before relying on it."
                    + (f" Note: {rule.citation.note.strip()}" if rule.citation.note.strip() else ""),
                )
            )

        if rule.kind == "limit":
            _deposit_limit_findings(rule, req, small_landlord_exception, result)

    if not any(d.applies and d.rule.kind == "disclosure" for d in result.decisions):
        result.findings.append(
            Finding(
                "warning",
                "disclosures",
                f"No disclosure rule fired for this property in {jurisdiction.name}. That can be correct "
                f"(a new-build with nothing to disclose), but it is worth a second look before sending.",
            )
        )

    return result
