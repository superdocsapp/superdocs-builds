"""Deciding what a re-run is allowed to touch.

The card asks that re-running after a data change "updates only what moved".
That is enforced here, and it turns on one distinction:

* A **numeric** fact changed, revenue is 1,455,000 instead of 1,400,000. The
  sentence still reads correctly; only the value in it is stale. Re-substitute
  the existing prose. **No model call, nothing billed.**
* A **text** fact changed, the direction flipped, a line item was renamed, the
  move crossed from "moved modestly" into "moved sharply". The wording itself
  is now wrong. That section, and only that section, is rewritten.

Everything else is kept byte-for-byte, and :func:`verify_untouched` proves it
rather than asserting it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .models import FactSet, ReportManifest, Section
from .numbers import substitute

Action = Literal["keep", "resubstitute", "regenerate"]


class UntouchedSectionChanged(AssertionError):
    """A section the plan promised not to touch did not render identically."""


@dataclass(slots=True)
class SectionPlan:
    section: Section
    action: Action
    reason: str
    changed_facts: tuple[str, ...] = ()


@dataclass(slots=True)
class UpdatePlan:
    """What a re-run intends to do, in reviewable form."""

    sections: list[SectionPlan] = field(default_factory=list)
    added_facts: tuple[str, ...] = ()
    removed_facts: tuple[str, ...] = ()
    changed_facts: tuple[str, ...] = ()
    series_added: tuple[str, ...] = ()
    series_removed: tuple[str, ...] = ()
    chart_stale: bool = False

    @property
    def is_noop(self) -> bool:
        return all(p.action == "keep" for p in self.sections) and not self.chart_stale

    @property
    def regenerating(self) -> list[SectionPlan]:
        return [p for p in self.sections if p.action == "regenerate"]

    @property
    def resubstituting(self) -> list[SectionPlan]:
        return [p for p in self.sections if p.action == "resubstitute"]

    @property
    def kept(self) -> list[SectionPlan]:
        return [p for p in self.sections if p.action == "keep"]

    @property
    def billable_operations(self) -> int:
        """Model calls this plan will spend. Re-substitution is free."""
        return 1 if self.regenerating else 0

    def summary(self) -> str:
        return (
            f"{len(self.kept)} kept, {len(self.resubstituting)} re-substituted, "
            f"{len(self.regenerating)} rewritten, "
            f"{self.billable_operations} operation(s) to spend"
        )


def diff_facts(previous: dict[str, str], current: FactSet) -> tuple[set[str], set[str], set[str]]:
    """(added, removed, changed) fact keys between a manifest and fresh facts."""
    now = current.digests()
    before_keys, now_keys = set(previous), set(now)
    added = now_keys - before_keys
    removed = before_keys - now_keys
    changed = {k for k in before_keys & now_keys if previous[k] != now[k]}
    return added, removed, changed


def _series_names(keys: set[str]) -> set[str]:
    return {k.split(".")[1] for k in keys if k.startswith("series.") and k.count(".") >= 2}


def plan_update(
    manifest: ReportManifest,
    facts: FactSet,
    *,
    chart_digest: str | None = None,
) -> UpdatePlan:
    """Work out the minimum set of changes that makes the report current."""
    added, removed, changed = diff_facts(manifest.fact_digests, facts)

    # A fact whose *rendered words* changed invalidates prose; a fact whose
    # magnitude changed only invalidates the value printed in it.
    text_changed = {k for k in changed if k in facts and facts[k].unit == "text"}
    numeric_changed = changed - text_changed

    plan = UpdatePlan(
        added_facts=tuple(sorted(added)),
        removed_facts=tuple(sorted(removed)),
        changed_facts=tuple(sorted(changed)),
        series_added=tuple(sorted(_series_names(added) - _series_names(set(manifest.fact_digests)))),
        series_removed=tuple(sorted(_series_names(removed) - _series_names(set(facts)))),
        chart_stale=bool(chart_digest and chart_digest != manifest.chart_digest),
    )

    for section in manifest.sections:
        keys = set(section.fact_keys)
        gone = keys & removed
        reworded = keys & text_changed
        revalued = keys & numeric_changed

        if gone:
            plan.sections.append(
                SectionPlan(
                    section,
                    "regenerate",
                    f"depends on {len(gone)} fact(s) no longer present in the sheet",
                    tuple(sorted(gone)),
                )
            )
        elif reworded:
            plan.sections.append(
                SectionPlan(
                    section,
                    "regenerate",
                    "wording depends on a fact whose text changed "
                    f"({', '.join(sorted(reworded))})",
                    tuple(sorted(reworded)),
                )
            )
        elif revalued:
            plan.sections.append(
                SectionPlan(
                    section,
                    "resubstitute",
                    f"{len(revalued)} figure(s) moved; wording still holds",
                    tuple(sorted(revalued)),
                )
            )
        else:
            plan.sections.append(SectionPlan(section, "keep", "no dependent fact changed"))

    return plan


def apply_plan(
    plan: UpdatePlan,
    facts: FactSet,
    regenerated: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render the new HTML for every section, keyed by section id.

    ``regenerated`` supplies fresh prose templates for sections the plan marked
    ``regenerate``; sections it does not cover keep their existing template,
    which is what makes a partially-rejected review safe to apply.
    """
    regenerated = regenerated or {}
    out: dict[str, str] = {}
    for entry in plan.sections:
        section = entry.section
        template = regenerated.get(section.id, section.template)
        out[section.id] = substitute(template, facts).text
    return out


def verify_untouched(plan: UpdatePlan, rendered: dict[str, str]) -> None:
    """Prove that every ``keep`` section came out byte-identical.

    This is the difference between claiming surgical precision and demonstrating
    it. It runs on every re-run, not just in tests.
    """
    drifted: list[str] = []
    for entry in plan.kept:
        before = entry.section.rendered
        after = rendered.get(entry.section.id)
        if before is None:
            continue  # never rendered before; nothing to hold it to
        if before != after:
            drifted.append(entry.section.id)
    if drifted:
        raise UntouchedSectionChanged(
            "sections marked untouched did not render identically: " + ", ".join(sorted(drifted))
        )
