"""Which document is likely to govern, given the sequence of events.

This is the part of the assigned build where it is easiest to start pretending. The temptation is
to hand both documents to a model and print whatever it says about which terms prevail. That
produces a confident legal conclusion with no reasoning behind it, on a question where being
confidently wrong costs a real buyer real money.

So no model decides this. Three commitments instead:

  1. **The sequence is explicit input.** Who sent what, when, and whether it was objected to. These
     are facts a contract manager knows; they are not inferred from prose.
  2. **The doctrine is data.** `rules/*.json` holds the named rules and their conditions. A
     different jurisdiction, or a firm's own house view, is a new file — not a code change.
  3. **The analysis names what it relied on**, and says INCONCLUSIVE when no rule matches rather
     than reaching for the closest one.

The output is a position to take to counsel, labelled as exactly that. It is not legal advice and
says so in every rendering.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EventKind(StrEnum):
    """The events that move a battle of the forms along.

    Deliberately small. Each one either carries terms, or is performance, or is an objection —
    those are the only three things the doctrine turns on.
    """

    PO_ISSUED = "po_issued"
    ACKNOWLEDGEMENT_RETURNED = "acknowledgement_returned"
    OBJECTION_SENT = "objection_sent"
    GOODS_DELIVERED = "goods_delivered"
    GOODS_ACCEPTED = "goods_accepted"
    INVOICE_PAID = "invoice_paid"

    @property
    def carries_terms(self) -> bool:
        return self in (EventKind.PO_ISSUED, EventKind.ACKNOWLEDGEMENT_RETURNED)

    @property
    def is_performance(self) -> bool:
        return self in (
            EventKind.GOODS_DELIVERED,
            EventKind.GOODS_ACCEPTED,
            EventKind.INVOICE_PAID,
        )


class Party(StrEnum):
    BUYER = "buyer"
    SUPPLIER = "supplier"


class SequenceEvent(BaseModel):
    """One thing that happened, on a date, done by one side."""

    model_config = ConfigDict(frozen=True)

    kind: EventKind
    on: date
    by: Party
    note: str | None = None

    @model_validator(mode="after")
    def _terms_documents_have_an_author(self) -> SequenceEvent:
        if self.kind is EventKind.OBJECTION_SENT and self.by is Party.SUPPLIER:
            # Not impossible in life, but this playbook models the buyer objecting to a supplier's
            # counter-offer. Rejecting it loudly beats silently analysing the wrong thing.
            raise ValueError(
                "this playbook models objections raised by the buyer; a supplier objection needs "
                "a rule set that covers it"
            )
        return self


class DerivedFacts(BaseModel):
    """What the rules are actually matched against. Every one is checkable against the sequence."""

    model_config = ConfigDict(frozen=True)

    last_terms_from: Party | None
    last_terms_on: date | None
    performance_followed_last_terms: bool
    objection_before_performance: bool
    first_performance_on: date | None

    @property
    def terms_were_exchanged(self) -> bool:
        """Whether any document carrying terms exists at all.

        Without this, a rule keyed on "nothing has been performed yet" also matches a sequence
        where nothing has *happened* yet — and reports an open exchange where there is no exchange.
        """
        return self.last_terms_from is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "last_terms_from": self.last_terms_from.value if self.last_terms_from else None,
            "performance_followed_last_terms": self.performance_followed_last_terms,
            "objection_before_performance": self.objection_before_performance,
            "terms_were_exchanged": self.terms_were_exchanged,
        }


class GoverningAnalysis(BaseModel):
    """A position, its reasoning, and the facts it depends on."""

    model_config = ConfigDict(frozen=True)

    doctrine: str
    rule_id: str | None
    likely_to_govern: Party | None
    conclusion: str = Field(min_length=1)
    reasoning: str = Field(min_length=1)
    facts_relied_on: DerivedFacts
    missing_to_decide: tuple[str, ...] = ()

    @property
    def is_inconclusive(self) -> bool:
        return self.rule_id is None

    # ClassVar, not a field: the disclaimer is a property of the analysis type itself and must not
    # be something a caller can construct without.
    DISCLAIMER: ClassVar[str] = (
        "This is a triage position derived from the recorded sequence of events and a stated "
        "doctrine, not legal advice. Confirm with counsel before relying on it."
    )

    def as_prose(self) -> str:
        lines = [
            f"Likely to govern: {self.conclusion}",
            "",
            f"Doctrine applied: {self.doctrine}",
        ]
        if self.rule_id:
            lines.append(f"Rule matched: {self.rule_id}")
        lines += ["", "Why:", self.reasoning, "", "Facts this depends on:"]
        facts = self.facts_relied_on
        lines.append(
            f"  - The last set of terms was sent by the "
            f"{facts.last_terms_from or 'neither party'}"
            + (f" on {facts.last_terms_on.isoformat()}" if facts.last_terms_on else "")
        )
        lines.append(
            "  - Performance "
            + ("followed" if facts.performance_followed_last_terms else "did NOT follow")
            + " those terms"
            + (
                f", first on {facts.first_performance_on.isoformat()}"
                if facts.first_performance_on
                else ""
            )
        )
        lines.append(
            "  - The buyer "
            + ("DID" if facts.objection_before_performance else "did not")
            + " object before performance"
        )
        if self.missing_to_decide:
            lines += ["", "To decide this, the sequence would also need:"]
            lines += [f"  - {item}" for item in self.missing_to_decide]
        lines += ["", self.DISCLAIMER]
        return "\n".join(lines)


class Playbook(BaseModel):
    """A named doctrine and its rules, loaded from JSON."""

    model_config = ConfigDict(frozen=True)

    doctrine: str
    summary: str
    authority_note: str
    rules: tuple[dict[str, Any], ...]
    inconclusive_because: str

    @classmethod
    def from_file(cls, path: str | Path) -> Playbook:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def derive_facts(events: Sequence[SequenceEvent]) -> DerivedFacts:
    """Reduce a sequence of events to the handful of facts the doctrine turns on.

    Ordered by date, so a caller may supply events in any order without changing the answer.
    """
    ordered = sorted(events, key=lambda event: event.on)

    terms = [event for event in ordered if event.kind.carries_terms]
    performance = [event for event in ordered if event.kind.is_performance]
    objections = [event for event in ordered if event.kind is EventKind.OBJECTION_SENT]

    last_terms = terms[-1] if terms else None
    first_performance = performance[0] if performance else None

    followed = bool(
        last_terms is not None
        and first_performance is not None
        and first_performance.on >= last_terms.on
    )

    # An objection only counts if it lands after the terms it objects to and before performance.
    objected = any(
        last_terms is not None
        and objection.on >= last_terms.on
        and (first_performance is None or objection.on <= first_performance.on)
        for objection in objections
    )

    return DerivedFacts(
        last_terms_from=last_terms.by if last_terms else None,
        last_terms_on=last_terms.on if last_terms else None,
        performance_followed_last_terms=followed,
        objection_before_performance=objected,
        first_performance_on=first_performance.on if first_performance else None,
    )


def analyse(events: Sequence[SequenceEvent], playbook: Playbook) -> GoverningAnalysis:
    """Match the derived facts against the playbook. Never guesses.

    The first rule whose conditions all hold wins; rules are ordered most-specific-first in the
    file, which keeps precedence readable by whoever maintains it rather than hidden in code.
    """
    facts = derive_facts(events)
    candidate = facts.as_dict()

    for rule in playbook.rules:
        conditions: dict[str, Any] = rule["when"]
        if all(candidate.get(key) == value for key, value in conditions.items()):
            conclusion = rule["conclusion"]
            governs = Party(conclusion) if conclusion in {"buyer", "supplier"} else None
            return GoverningAnalysis(
                doctrine=playbook.doctrine,
                rule_id=rule["id"],
                likely_to_govern=governs,
                conclusion=_phrase(conclusion),
                reasoning=rule["because"],
                facts_relied_on=facts,
            )

    return GoverningAnalysis(
        doctrine=playbook.doctrine,
        rule_id=None,
        likely_to_govern=None,
        conclusion="Cannot be determined from the sequence recorded",
        reasoning=playbook.inconclusive_because,
        facts_relied_on=facts,
        missing_to_decide=_what_is_missing(facts),
    )


def _phrase(conclusion: str) -> str:
    return {
        "buyer": "The buyer's terms",
        "supplier": "The supplier's terms",
        "unresolved": "Neither — the exchange is still open",
    }.get(conclusion, conclusion)


def _what_is_missing(facts: DerivedFacts) -> tuple[str, ...]:
    """Name the gap rather than filling it."""
    missing: list[str] = []
    if facts.last_terms_from is None:
        missing.append(
            "a document that carries terms — a purchase order or an acknowledgement — with its date"
        )
    if facts.first_performance_on is None:
        missing.append(
            "whether anything was performed: goods delivered or accepted, or an invoice paid"
        )
    return tuple(missing)
