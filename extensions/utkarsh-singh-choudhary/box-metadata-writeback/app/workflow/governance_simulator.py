"""Simulates the Box-native automation the card says our written metadata
is supposed to drive: "Those fields then drive Box's own retention,
search, and workflow rules, so the document work feeds the governance
the enterprise already runs."

Nothing else in this build proves that sentence -- everywhere else we
stop at "metadata was written." This module reads exactly what's in the
Box metadata template (the same fields Box's own retention policies,
search facets, and workflow automations would read) and computes the
same three classes of outcome Box itself would compute from them:

  1. retention / disposition eligibility  (Box Retention Policies)
  2. search facets a real user could filter/find this file by (Box Search)
  3. which workflow(s) this file's current state would enter (Box Relay)

Every outcome cites the exact metadata field and value that produced it,
because "prove the loop closes" only means something if the reasoning is
inspectable, not just a verdict.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Optional

# Mirrors the mapping in app/workflow/pipeline.py::_retention_category_for.
# A real Box deployment would configure these durations as actual
# Retention Policy objects (Box lets you attach a policy per
# classification); this is that same policy table, expressed as code so
# the simulator can compute a concrete eligible-on date instead of just
# repeating the category name.
_RETENTION_DURATIONS_YEARS: dict[str, int] = {
    "contracts-7yr": 7,
    "financial-5yr": 5,
    "correspondence-3yr": 3,
    "policy-indefinite": 0,  # 0 means "never eligible on a schedule"
    "uncategorized-review": 0,  # never auto-eligible; needs a human to categorize first
}


@dataclass
class GovernanceOutcome:
    file_id: str
    computed_at: str

    # -- retention / disposition ------------------------------------------------
    retention_category: Optional[str]
    retention_anchor_field: Optional[str]  # which date field the clock starts from
    retention_anchor_date: Optional[str]
    disposition_eligible_on: Optional[str]
    disposition_eligible_now: bool
    disposition_blocked_by_legal_hold: bool
    retention_reasoning: list[str] = field(default_factory=list)

    # -- search -------------------------------------------------------------------
    search_facets: dict[str, str] = field(default_factory=dict)
    search_reasoning: list[str] = field(default_factory=list)

    # -- workflow -------------------------------------------------------------------
    workflows_triggered: list[str] = field(default_factory=list)
    workflows_blocked: list[str] = field(default_factory=list)
    workflow_reasoning: list[str] = field(default_factory=list)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def compute_governance_outcome(
    file_id: str,
    metadata: dict[str, Any],
    legal_hold: bool,
    retention_policy_locked: bool,
    pending_review_field_names: list[str],
    today: Optional[date] = None,
) -> GovernanceOutcome:
    today = today or date.today()
    outcome = GovernanceOutcome(
        file_id=file_id,
        computed_at=today.isoformat(),
        retention_category=metadata.get("retention_category"),
        retention_anchor_field=None,
        retention_anchor_date=None,
        disposition_eligible_on=None,
        disposition_eligible_now=False,
        disposition_blocked_by_legal_hold=legal_hold or retention_policy_locked,
    )

    # -- 1. retention / disposition -------------------------------------------------
    category = outcome.retention_category
    if not category:
        outcome.retention_reasoning.append(
            "no retention_category in metadata -- file has not been classified yet, "
            "Box cannot attach a retention policy to it"
        )
    else:
        duration_years = _RETENTION_DURATIONS_YEARS.get(category)
        if duration_years is None:
            outcome.retention_reasoning.append(
                f"retention_category={category!r} is not a recognized policy; "
                "treating as never auto-eligible pending a human decision"
            )
        elif duration_years == 0:
            outcome.retention_reasoning.append(
                f"retention_category={category!r} has no fixed schedule "
                "(policy-indefinite or needs manual categorization) -- never auto-eligible"
            )
        else:
            # Prefer expiration_date as the anchor (a contract's clock
            # should start when its term ends, not when it began); fall
            # back to effective_date if there's no expiration_date --
            # e.g. an invoice has no expiration_date at all.
            anchor_field = "expiration_date" if metadata.get("expiration_date") else "effective_date"
            anchor_value = metadata.get(anchor_field)
            anchor_date = _parse_date(anchor_value)
            if anchor_date is None:
                outcome.retention_reasoning.append(
                    f"retention_category={category!r} requires a {duration_years}-year "
                    f"clock, but neither expiration_date nor effective_date is present in "
                    "metadata to anchor it from -- disposition eligibility cannot be computed"
                )
            else:
                outcome.retention_anchor_field = anchor_field
                outcome.retention_anchor_date = anchor_date.isoformat()
                eligible_on = date(anchor_date.year + duration_years, anchor_date.month, anchor_date.day)
                outcome.disposition_eligible_on = eligible_on.isoformat()
                outcome.retention_reasoning.append(
                    f"retention_category={category!r} -> {duration_years} years from "
                    f"{anchor_field}={anchor_value!r} -> eligible on {eligible_on.isoformat()}"
                )
                if outcome.disposition_blocked_by_legal_hold:
                    outcome.retention_reasoning.append(
                        "legal_hold/retention_policy_locked is set on this file -- Box "
                        "NEVER disposes a file under hold regardless of the schedule above; "
                        "this mirrors the pipeline's own refusal to touch governance fields"
                    )
                else:
                    outcome.disposition_eligible_now = today >= eligible_on
                    outcome.retention_reasoning.append(
                        f"today ({today.isoformat()}) is "
                        + ("on or past" if outcome.disposition_eligible_now else "before")
                        + " the eligible date -> disposition eligible = "
                        + str(outcome.disposition_eligible_now)
                    )

    # -- 2. search facets -------------------------------------------------------------
    # These are the fields a real Box Search / Box Shield admin console
    # would expose as filterable facets, because they're exactly the
    # structured metadata template fields Box indexes for search.
    facet_fields = ("doc_class", "counterparty_name", "retention_category")
    for f in facet_fields:
        value = metadata.get(f)
        if value:
            outcome.search_facets[f] = value
            outcome.search_reasoning.append(f"{f}={value!r} is written and searchable/filterable in Box")
        else:
            outcome.search_reasoning.append(f"{f} not present in metadata -- not filterable for this file")

    # -- 3. workflow -------------------------------------------------------------------
    doc_class = metadata.get("doc_class")
    normalized = metadata.get("normalized")
    if pending_review_field_names:
        outcome.workflows_blocked.append("auto-file-to-final-location")
        outcome.workflow_reasoning.append(
            f"fields still pending human review ({', '.join(pending_review_field_names)}) -- "
            "a Box Relay workflow gated on 'metadata complete' would not fire yet"
        )
    if doc_class in ("contract", "amendment") and normalized and not pending_review_field_names:
        outcome.workflows_triggered.append("contract-review-workflow")
        outcome.workflow_reasoning.append(
            f"doc_class={doc_class!r} and normalized=True with no pending reviews -- "
            "a Box Relay rule keyed on those two fields would route this to legal review"
        )
    if outcome.disposition_eligible_now:
        outcome.workflows_triggered.append("disposition-review-workflow")
        outcome.workflow_reasoning.append(
            "disposition_eligible_now=True -- a Box Relay retention-expiry rule would "
            "notify the record owner for disposition sign-off"
        )
    if not outcome.workflows_triggered and not outcome.workflows_blocked:
        outcome.workflow_reasoning.append("no workflow conditions matched -- file stays in steady state")

    return outcome
