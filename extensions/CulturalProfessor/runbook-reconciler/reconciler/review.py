"""The human gate.

Everything this tool does to a document passes through here. That is not a
policy statement bolted on at the end — `apply_approved` reads
`decision = 'approved'` out of the register and there is no other way to set it,
so a finding nobody looked at cannot be written.

## Why the queue logic is separate from the terminal

`ReviewQueue` holds the decisions and knows nothing about prompts, colours or
`input()`. The terminal loop is thirty lines on top of it, and the MCP server
calls exactly the same methods. Behaviour four of the brief asks that a machine
be able to drive the whole flow *including the gate*; that is only true if the
gate is not made of `input()` calls, and it is much easier to write it this way
first than to extract it later.

## What "item by item" means here

Rejecting one finding leaves the rest. That sounds obvious and it is exactly
what a batch-shaped implementation gets wrong: the natural way to write this is
to collect approvals and apply them together, and then a single rejection either
discards the batch or is silently included. Decisions are recorded one at a time
against `finding_id`, and the commit reads back only what was approved.

## What a reviewer is shown

The subject, what the page says, what the infrastructure says, the file and line
that proves it, and the exact replacement. Not a diff of the whole page: the
change is one value, and showing a page diff to review a value is how people
learn to approve without reading.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from reconciler.apply import ApplyResult, PageSource, apply_approved
from reconciler.claims import Claim, Finding
from reconciler.register import Register


@dataclass(frozen=True)
class ReviewItem:
    """One decision, with everything needed to make it."""

    finding: Finding
    claim: Claim | None

    @property
    def finding_id(self) -> str:
        return self.finding.finding_id

    @property
    def editable(self) -> bool:
        return bool(self.claim and self.claim.anchor.editable)

    @property
    def has_proposal(self) -> bool:
        return bool(self.finding.proposed)

    def lines(self) -> list[str]:
        page = f"page {self.finding.page_id}" if self.finding.page_id else "estate-wide"
        out = [
            f"{page} · {self.finding.subject}",
            f"  the runbook says : {self.claim.asserted if self.claim else '—'}",
            f"  the estate says  : {self.finding.observed or '—'}",
            f"  evidence         : {self.finding.evidence_file}:{self.finding.evidence_line or 1}",
        ]
        if self.claim:
            out.append(f"  passage          : {_trim(self.claim.excerpt)}")
        if self.finding.proposed:
            out.append(
                f"  proposed change  : {self.claim.asserted if self.claim else '?'} "
                f"→ {self.finding.proposed}"
            )
        elif not self.editable:
            reason = (self.claim.anchor.refusal if self.claim else None) or "not editable"
            out.append(f"  cannot be edited : {reason}")
            out.append("  approving this posts a comment for a human rather than editing")
        else:
            out.append("  no replacement text yet — run `rr propose` first")
        if self.finding.detail:
            out.append(f"  why it matters   : {_trim(self.finding.detail, 200)}")
        return out


class ReviewQueue:
    """Decisions in, one write out. No terminal anywhere in here."""

    def __init__(self, register: Register) -> None:
        self.register = register

    def items(self) -> list[ReviewItem]:
        return [
            ReviewItem(finding=finding, claim=self.register.claim(finding.claim_id or ""))
            for finding in self.register.review_queue()
        ]

    def approve(self, finding_id: str) -> None:
        self.register.decide(finding_id, "approved")

    def reject(self, finding_id: str) -> None:
        """Rejected, and recorded as rejected.

        Not deleted. The next sweep finds the same drift and would re-queue it;
        a recorded rejection is what stops the tool asking the same question
        every night, and it is also the honest record that somebody decided the
        document was right and the infrastructure was wrong.
        """
        self.register.decide(finding_id, "rejected")

    def commit(self, source: PageSource) -> ApplyResult:
        """Write what was approved, and only what was approved."""
        return apply_approved(self.register, source)

    def summary(self) -> dict[str, int]:
        return self.register.summary()


def run_terminal_review(
    queue: ReviewQueue,
    source: PageSource,
    prompt: Callable[[str], str] | None = None,
    output: Callable[[str], None] = print,
    auto: str | None = None,
) -> ApplyResult:
    """The interactive loop, and the thinnest possible layer over the queue.

    `auto` drives it without a terminal — `"approve"` or `"reject"` — which is
    what the tests and the CI action use. It is a deliberate parameter rather
    than an environment variable, so a script cannot approve everything by
    accident because a variable was left set.
    """
    ask = prompt or input
    items = queue.items()
    if not items:
        output("nothing to review: no undecided contradictions in the register.")
        return ApplyResult()

    output(f"{len(items)} finding(s) to review. a=approve  r=reject  s=skip  q=quit\n")
    decided = 0
    for index, item in enumerate(items, start=1):
        output(f"[{index}/{len(items)}]")
        for line in item.lines():
            output(line)

        answer = auto[0] if auto else ask("  approve, reject, skip? [a/r/s/q] ").strip().lower()
        if answer == "q":
            output("stopped. decisions already made are kept; the rest stay in the queue.")
            break
        if answer == "a":
            queue.approve(item.finding_id)
            decided += 1
        elif answer == "r":
            queue.reject(item.finding_id)
            decided += 1
        output("")

    result = queue.commit(source)
    output(result.summary_line() or "nothing to apply.")
    for finding_id, why in result.escalated:
        output(f"  escalated {finding_id}: {why}")
    for page_id in result.stranded:
        output(f"  STRANDED page {page_id}: it was written and could not be restored.")
    return result


def iter_pages(items: list[ReviewItem]) -> Iterator[tuple[str, list[ReviewItem]]]:
    """Grouped by page, for a reviewer who would rather go page at a time."""
    by_page: dict[str, list[ReviewItem]] = {}
    for item in items:
        by_page.setdefault(item.finding.page_id or "", []).append(item)
    yield from sorted(by_page.items())


def _trim(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


__all__ = ["ReviewItem", "ReviewQueue", "iter_pages", "run_terminal_review"]
