"""Alerts and runbooks, checked against each other in both directions.

The vertical checks ask "is what this page says true". This asks the question
nobody's linter asks: **is there a page at all, and does the alert know about
it.** Those are different failures with different fixes, and a coverage report
that collapses them is a report that tells you a number and not what to do.

Four outcomes, and the third is the one that justifies doing this bidirectionally:

- **orphan alert** — no `runbook_url`, and nothing in the space is about it.
  Somebody gets paged at three in the morning with nothing to read.
- **dead runbook link** — a `runbook_url` pointing at a page that is not there.
  Worse than having none, because it looks covered on a coverage dashboard.
- **unlinked runbook** — a good runbook exists and the alert does not point at
  it. One-directional coverage reports this identically to the first case; it is
  not the same problem, and the fix is a one-line annotation rather than an
  afternoon of writing.
- **orphan runbook** — a page about a service that no longer exists. Found by
  the vertical pass, which has the entity resolution, and counted here.

None of these are editable. There is no sentence to fix: the answer is an
annotation, a new page or an archived one, and all three are somebody's
decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from reconciler.claims import Finding
from reconciler.confluence.local import PageRef
from reconciler.estate import Estate


@dataclass(frozen=True)
class Coverage:
    """The numbers behind the report, kept separate from their wording."""

    alerts_total: int = 0
    alerts_with_resolving_runbook: int = 0
    alerts_with_dead_runbook_link: int = 0
    alerts_without_runbook_url: int = 0
    alerts_unlinked_but_documented: int = 0
    runbook_pages_total: int = 0
    orphan_runbook_pages: tuple[str, ...] = ()
    dead_dashboard_links: int = 0
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def documented_fraction(self) -> float:
        if not self.alerts_total:
            return 0.0
        return self.alerts_with_resolving_runbook / self.alerts_total

    def headline(self) -> str:
        """The line this whole stage exists to be able to print."""
        return (
            f"{self.alerts_total} alerts · "
            f"{self.alerts_with_resolving_runbook} have runbooks · "
            f"{self.alerts_with_dead_runbook_link} dead links · "
            f"{len(self.orphan_runbook_pages)} runbooks referencing resources that no longer "
            f"exist · {self.alerts_without_runbook_url} alerts with no runbook"
        )


def check_coverage(
    estate: Estate,
    pages: list[PageRef],
    page_text: dict[str, str] | None = None,
    orphan_pages: tuple[str, ...] = (),
    dead_dashboard_links: int = 0,
) -> Coverage:
    """Both directions at once, because they share the same joins."""
    page_ids = {page.page_id for page in pages}
    page_text = page_text or {}
    findings: list[Finding] = []

    resolving = dead = missing = unlinked = 0

    for alert in estate.alerts:
        page_id = alert.runbook_page_id
        if page_id and page_id in page_ids:
            resolving += 1
            continue

        if page_id:
            dead += 1
            findings.append(
                Finding(
                    rule_id="dead-runbook-link",
                    kind="coverage",
                    subject=f"alert:{alert.name}:runbook_url",
                    verdict="contradicts",
                    evidence_file=alert.source.file,
                    evidence_line=alert.source.line,
                    # The URL as written, not a paraphrase of it. A finding that
                    # says "page 1099 is missing" makes the reader go and look up
                    # what the annotation actually contains; quoting it does not.
                    observed=(
                        f"runbook_url points at {alert.runbook_url}, and page {page_id} is "
                        f"not in the reconciled space"
                    ),
                    detail=(
                        f"{alert.name} links to a runbook that does not exist. This is worse "
                        f"than having no link: it counts as covered on every coverage "
                        f"dashboard, and the responder finds out at 3am"
                    ),
                    tags=("coverage", "comment-only"),
                )
            )
            continue

        missing += 1
        documented_on = _page_mentioning(alert.name, page_text)
        if documented_on:
            unlinked += 1
            findings.append(
                Finding(
                    rule_id="unlinked-runbook",
                    kind="coverage",
                    subject=f"alert:{alert.name}:runbook_url",
                    verdict="contradicts",
                    evidence_file=alert.source.file,
                    evidence_line=alert.source.line,
                    # No `page_id`, deliberately. The gap is in the alerting rule,
                    # not on the page, and there is no passage to anchor to or
                    # edit -- the fix is an annotation in a YAML file this tool
                    # will never write. Naming the page here would put an
                    # uneditable finding into that page's edit queue.
                    observed=(
                        f"no runbook_url, although page {documented_on} documents this alert"
                    ),
                    detail=(
                        f"a runbook for {alert.name} exists and is not linked, so the responder "
                        f"never finds it. The fix is a `runbook_url` annotation, not a new page"
                    ),
                    tags=("coverage", "comment-only"),
                )
            )
        else:
            findings.append(
                Finding(
                    rule_id="orphan-alert",
                    kind="coverage",
                    subject=f"alert:{alert.name}",
                    verdict="contradicts",
                    evidence_file=alert.source.file,
                    evidence_line=alert.source.line,
                    observed="no runbook_url and no page in the space mentions it",
                    detail=(
                        f"{alert.name} pages a human with nothing to read. Severity "
                        f"{alert.severity or 'unset'}, owned by {alert.team or 'nobody declared'}"
                    ),
                    tags=("coverage", "comment-only"),
                )
            )

    return Coverage(
        alerts_total=len(estate.alerts),
        alerts_with_resolving_runbook=resolving,
        alerts_with_dead_runbook_link=dead,
        alerts_without_runbook_url=missing,
        alerts_unlinked_but_documented=unlinked,
        runbook_pages_total=len(pages),
        orphan_runbook_pages=orphan_pages,
        dead_dashboard_links=dead_dashboard_links,
        findings=tuple(findings),
    )


def _page_mentioning(alert_name: str, page_text: dict[str, str]) -> str | None:
    """Which page documents this alert, if the alert does not say.

    An exact name match, not a fuzzy one. A runbook that names the alert is
    documenting it; a page that merely discusses the same service is not, and
    telling a team "you already have a runbook for this" when they do not is the
    kind of wrong that gets a tool switched off.

    Which is why this is bounded rather than `alert_name in text`. Alert names
    nest: an estate with `PaymentsApiHighLatency` and
    `PaymentsApiHighLatencyWarning` has the first as a prefix of the second, and
    a plain substring test reports the warning as documented by the page that
    only ever mentions the critical one. The finding then tells the team to add
    a `runbook_url` annotation pointing at a page that does not describe their
    alert — worse than the `orphan-alert` it displaced, because it reads as
    nearly done.
    """
    bounded = re.compile(rf"\b{re.escape(alert_name)}\b")
    for page_id, text in sorted(page_text.items()):
        if bounded.search(text):
            return page_id
    return None


__all__ = ["Coverage", "check_coverage"]
