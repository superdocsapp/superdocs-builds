"""Change propagation — the part the card is actually about.

*"A change to the delivery date or the bandwidth updates every dependent
document."*

The cheap way to satisfy that sentence is to re-render all six documents from
the new record and re-upload them. It would produce correct output and prove
nothing: it is not an update, it is a rebuild that happens to land in the same
place, and it throws away every edit anyone made to the pack in between.

So this does the other thing. For a changed field it computes which documents
carry it, sends **one targeted instruction per document** naming the old value
and the new one, and holds each proposed change at a human gate before it
applies. Documents that do not carry the field are not contacted at all, and
that is checked afterwards rather than assumed.

The instruction is deliberately narrow. "Change the ready-for-service date"
invites a helpful model to also update a sentence about the programme; naming
the exact old string and demanding nothing else changes does not.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from packet.build import Pack
from packet.diagram import diagram_signature
from packet.order import BY_PATH, Order, OrderError
from packet.superdocs import SuperDocs, SuperDocsError
from packet.templates import BY_SLUG

log = logging.getLogger(__name__)

Reviewer = Callable[[dict[str, Any], "PlannedEdit"], bool]


@dataclass
class FieldChange:
    path: str
    before: Any
    after: Any
    before_text: str
    after_text: str

    @property
    def label(self) -> str:
        return BY_PATH[self.path].label


@dataclass
class PlannedEdit:
    slug: str
    title: str
    audience: str
    document_id: str | None
    session_id: str
    instruction: str
    changes: list[FieldChange]
    regenerate_diagram: bool = False


@dataclass
class EditOutcome:
    slug: str
    audience: str
    applied: int = 0
    rejected: int = 0
    skipped_reason: str | None = None
    job_id: str | None = None
    error: str | None = None
    proposed: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PropagationReport:
    changes: list[FieldChange]
    planned: list[PlannedEdit]
    untouched: list[str]
    outcomes: list[EditOutcome] = field(default_factory=list)
    repairs: list[EditOutcome] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def applied(self) -> int:
        return sum(o.applied for o in self.outcomes + self.repairs)

    @property
    def rejected(self) -> int:
        return sum(o.rejected for o in self.outcomes + self.repairs)

    @property
    def failed(self) -> list[EditOutcome]:
        return [o for o in self.outcomes + self.repairs if o.error]


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def diff_orders(before: Order, after: Order) -> list[FieldChange]:
    """Every declared field whose rendered value moved.

    Compares the *rendered* value, not the raw one, because that is what the
    documents contain: `18400` and `18400.0` are the same monthly charge and
    must not trigger six edits that change nothing.
    """
    changes: list[FieldChange] = []
    for path in BY_PATH:
        b_raw, a_raw = before.raw(path), after.raw(path)
        b_text = before.value(path, audience="internal")
        a_text = after.value(path, audience="internal")
        if b_text != a_text:
            changes.append(FieldChange(path, b_raw, a_raw, b_text, a_text))
    return changes


def plan(
    changes: Iterable[FieldChange],
    packs: dict[str, Pack],
    *,
    before: Order,
    after: Order,
) -> tuple[list[PlannedEdit], list[str]]:
    """Work out exactly which documents to contact, and with what.

    Returns the planned edits and the slugs deliberately left alone, because
    "what did you *not* touch" is half the claim being made.
    """
    changes = list(changes)
    diagram_moved = diagram_signature(before) != diagram_signature(after)

    planned: list[PlannedEdit] = []
    touched: set[tuple[str, str]] = set()

    for audience, pack in packs.items():
        for doc in pack.documents:
            spec = BY_SLUG[doc.slug]
            visible = spec.fields if audience == "internal" else spec.customer_fields
            relevant = [c for c in changes if c.path in visible]
            needs_diagram = spec.has_diagram and diagram_moved
            if not relevant and not needs_diagram:
                continue

            planned.append(
                PlannedEdit(
                    slug=doc.slug,
                    title=doc.title,
                    audience=audience,
                    document_id=doc.document_id,
                    session_id=doc.session_id,
                    instruction=instruction_for(
                        relevant, regenerate_diagram=needs_diagram, after=after,
                        slug=doc.slug,
                    ),
                    changes=relevant,
                    regenerate_diagram=needs_diagram,
                )
            )
            touched.add((audience, doc.slug))

    untouched = [
        f"{audience}/{doc.slug}"
        for audience, pack in packs.items()
        for doc in pack.documents
        if (audience, doc.slug) not in touched
    ]
    return planned, untouched


def _diagram_section_body(after: Order) -> str:
    """The whole diagram section, ready to be dropped in as one unit."""
    from packet.diagram import as_designed_diagram

    return (
        f"<h2>1. As-designed configuration</h2>\n"
        f"<p>The diagram below is generated from the order record. It shows "
        f"{after.value('service.bandwidth_mbps')} "
        f"{after.value('service.product')} between {after.value('sites.a.label')} and "
        f"{after.value('sites.b.label')} with {after.value('service.diversity')}.</p>\n"
        + as_designed_diagram(after)
    )


def instruction_for(
    changes: list[FieldChange],
    *,
    regenerate_diagram: bool,
    after: Order,
    slug: str = "",
) -> str:
    """The message sent to SuperDocs for one document.

    Written the way you would brief a careful colleague, with the old and new
    strings quoted exactly, and with an explicit instruction not to tidy
    anything else up. Vague prompts invite wide edits — the docs say so and it
    is true.

    **Colliding old values are anchored on the label instead.** Route diversity
    and protection scheme both read "None — single path" on an unprotected
    circuit. Telling a model to replace that string with two different values in
    the same breath is not a hard instruction, it is a contradiction — and the
    live run proved it: the model resolved it one way in one document and the
    other way in another, so the internal and customer packs drifted apart on a
    contract term. Where two changed fields share a before value, the
    instruction names the labelled row and stops quoting the ambiguous string.
    """
    collisions = Counter(c.before_text for c in changes)

    lines = [
        "Apply these specific corrections to this document. Make only these changes."
        if changes
        else "Replace the diagram in this document. Change nothing else.",
        "",
    ]
    for i, change in enumerate(changes, start=1):
        if collisions[change.before_text] > 1:
            others = sorted(
                c.label for c in changes
                if c.before_text == change.before_text and c is not change
            )
            lines.append(
                f'{i}. In the row or field labelled "{change.label}" — and only '
                f"that one — set the value to \"{change.after_text}\". Its current "
                f'value is "{change.before_text}". Be careful: '
                f"{', '.join(others)} currently shows the same text and is handled "
                f"separately below; do not change it under this item."
            )
        else:
            lines.append(
                f'{i}. Wherever the document says "{change.before_text}" as the '
                f"{change.label.lower()}, replace it with \"{change.after_text}\". "
                f"There may be more than one occurrence; change all of them."
            )
    if regenerate_diagram:
        from packet.diagram import as_designed_diagram
        from packet.templates import BY_SLUG

        section = ""
        if slug and slug in BY_SLUG:
            section = BY_SLUG[slug].diagram_section

        if section:
            # A section rewrite is atomic — the docs are explicit that it
            # replaces heading-to-next-heading as one unit. "Replace this
            # diagram" is an ordinary edit, and a live run showed the model
            # satisfying it by tweaking labels in place: the bandwidth updated
            # and the topology stayed single-path.
            lines += [
                "",
                f"{len(changes) + 1}. Rewrite the section headed \"{section}\" so that it "
                f"contains exactly the content below and nothing else. Replace the whole "
                f"section, including the existing diagram — do not edit the old diagram in "
                f"place.",
                "",
                _diagram_section_body(after),
            ]
        else:
            lines += [
                "",
                f"{len(changes) + 1}. Replace the existing mermaid diagram with exactly this "
                "one, keeping it in the same position:",
                "",
                as_designed_diagram(after),
            ]
    lines += [
        "",
        "Do not reword anything else. Do not change any other number, date, name or "
        "heading. Do not add commentary, notes about the change, or a revision history. "
        "If a value I named does not appear in this document, skip that item and say so "
        "rather than changing something similar.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def apply_plan(
    client: SuperDocs,
    planned: list[PlannedEdit],
    *,
    review: Reviewer,
    model_tier: str = "pro",
    thinking_depth: str = "balanced",
    poll_timeout: float = 420.0,
    on_progress: Callable[[str, str], None] | None = None,
) -> list[EditOutcome]:
    """Send each edit, hold it at the gate, apply exactly what is approved.

    ``pro`` by default rather than ``core``: these are contract documents where
    a wrong word costs a re-issue, and the docs are explicit that a more capable
    tier is the fix for "the AI edited sections you didn't ask about".
    """
    outcomes: list[EditOutcome] = []

    for edit in planned:
        outcome = EditOutcome(slug=edit.slug, audience=edit.audience)

        # Bound per iteration rather than closing over the loop variable, so
        # the callbacks handed to wait_for_job cannot report against the wrong
        # document if the loop ever becomes concurrent.
        def note(msg: str, _who: str = f"{edit.audience}/{edit.slug}") -> None:
            if on_progress:
                on_progress(_who, msg)

        if edit.document_id is None:
            outcome.skipped_reason = (
                "no SuperDocs document id in the manifest — rebuild the pack"
            )
            outcomes.append(outcome)
            continue

        try:
            note("sending")
            job_id = client.chat_async(
                edit.instruction,
                session_id=edit.session_id,
                document_id=edit.document_id,
                approval_mode="ask_every_time",
                model_tier=model_tier,
                thinking_depth=thinking_depth,
            )
            outcome.job_id = job_id

            job = client.wait_for_job(
                job_id,
                timeout=poll_timeout,
                on_tick=lambda status, _job, _n=note: _n(status),
            )

            # Two different pauses share the status 'awaiting_approval'. Calling
            # the wrong endpoint returns 409, so branch before deciding.
            rounds = 0
            while job.get("status") == "awaiting_approval" and rounds < 5:
                rounds += 1
                if client.awaiting_kind(job) == "continue_prompt":
                    note("large edit paused; continuing")
                    client.continue_chat(edit.session_id, job_id, keep_going=True)
                    job = client.wait_for_job(job_id, timeout=poll_timeout)
                    continue

                proposed = client.pending_changes(job)
                outcome.proposed.extend(proposed)
                if not proposed:
                    note("paused with no proposed changes; stopping")
                    break

                decisions = []
                for change in proposed:
                    approved = review(change, edit)
                    decisions.append(
                        {
                            "change_id": change.get("change_id"),
                            "approved": approved,
                            **(
                                {}
                                if approved
                                else {"feedback": "Rejected by the delivery manager."}
                            ),
                        }
                    )
                    outcome.applied += 1 if approved else 0
                    outcome.rejected += 0 if approved else 1

                note(f"approving {sum(1 for d in decisions if d['approved'])} of {len(decisions)}")
                client.approve(
                    edit.session_id,
                    job_id,
                    approved=True,  # required at top level even for batch shapes
                    changes=decisions,
                )
                job = client.wait_for_job(job_id, timeout=poll_timeout)

            if job.get("status") == "failed":
                outcome.error = str(job.get("error") or "the job failed without a reason")
            note("done")

        except SuperDocsError as exc:
            # One document failing must not abandon the other five. A partial
            # propagation that says which parts landed is recoverable; one that
            # dies halfway and says nothing is not.
            outcome.error = str(exc)
            log.error("propagation failed on %s/%s: %s", edit.audience, edit.slug, exc)

        outcomes.append(outcome)

    return outcomes


def propagate(
    client: SuperDocs,
    *,
    before: Order,
    after: Order,
    packs: dict[str, Pack],
    review: Reviewer,
    model_tier: str = "pro",
    repair: bool = True,
    on_progress: Callable[[str, str], None] | None = None,
) -> PropagationReport:
    started = time.perf_counter()
    changes = diff_orders(before, after)
    if not changes:
        raise OrderError(
            "nothing changed between the two order records — no edit would be honest"
        )
    planned, untouched = plan(changes, packs, before=before, after=after)
    report = PropagationReport(changes=changes, planned=planned, untouched=untouched)
    if client.ledger.dry_run:
        report.seconds = time.perf_counter() - started
        return report

    report.outcomes = apply_plan(
        client, planned, review=review, model_tier=model_tier, on_progress=on_progress
    )
    if repair:
        report.repairs = _repair_pass(
            client, planned, after=after, packs=packs, review=review,
            model_tier=model_tier, on_progress=on_progress,
            applied_outcomes=report.outcomes,
        )
    report.seconds = time.perf_counter() - started
    return report


def _repair_pass(
    client: SuperDocs,
    planned: list[PlannedEdit],
    *,
    after: Order,
    packs: dict[str, Pack],
    review: Reviewer,
    model_tier: str,
    on_progress: Callable[[str, str], None] | None,
    applied_outcomes: list[EditOutcome] | None = None,
) -> list[EditOutcome]:
    """One bounded retry for fields a multi-field turn did not land.

    Measured on live runs: a turn carrying one field change applies it
    reliably; a turn carrying four applies some and quietly skips others. The
    model is not lying — the reply says what it did — but the pack is wrong
    either way.

    Rather than raise the per-document cost for everyone by always sending one
    field per turn, this reads back what actually landed and re-sends **only
    the fields that are still missing, one field per turn**. A clean
    propagation costs nothing extra; a partial one costs one operation per
    missed field. Exactly one round: if a field will not land twice, that is a
    finding for a person, not a loop to spin in.
    """
    from packet.verify import live_text, reset_body_cache

    reset_body_cache()
    outcomes: list[EditOutcome] = []

    # A document where the reviewer rejected something is never repaired. The
    # repair pass exists to catch a model that quietly skipped a field, not to
    # overrule a person who looked at a change and said no — and it cannot tell
    # the two apart from the outside, so it defers to the human.
    rejected_docs = {
        (o.audience, o.slug) for o in (applied_outcomes or []) if o.rejected
    }

    for edit in planned:
        if not edit.document_id:
            continue
        if (edit.audience, edit.slug) in rejected_docs:
            if on_progress:
                on_progress(
                    f"{edit.audience}/{edit.slug}",
                    "not repaired — a change here was rejected by the reviewer",
                )
            continue
        pack = packs[edit.audience]
        doc = pack.by_slug(edit.slug)
        if doc is None:
            continue
        text = live_text(client, pack, doc)
        missing = [
            c for c in edit.changes
            if after.value(c.path, audience=edit.audience) not in text
        ]

        # The diagram needs its own check. A field value can be present
        # elsewhere in the document while the diagram still describes the old
        # configuration — which is exactly what happened on a live run: the
        # scope of work listed dual path in its table and drew a single path.
        # The declaration comments make that checkable instead of arguable.
        diagram_stale = False
        if edit.regenerate_diagram:
            declared = dict(re.findall(r"%% design:(\w+)=([^\n<]+)", text))
            want_bw = after.value("service.bandwidth_mbps", audience=edit.audience)
            want_div = (
                "dual"
                if str(after.raw("service.diversity", "none")).lower() in {"dual", "diverse"}
                else "single"
            )
            diagram_stale = (
                declared.get("bandwidth", "").strip() != want_bw
                or declared.get("diversity", "").strip() != want_div
            )

        if not missing and not diagram_stale:
            continue

        if on_progress:
            what = f"{len(missing)} field(s)" + (" and the diagram" if diagram_stale else "")
            on_progress(f"{edit.audience}/{edit.slug}", f"repairing {what}")

        if diagram_stale:
            redraw = PlannedEdit(
                slug=edit.slug, title=edit.title, audience=edit.audience,
                document_id=edit.document_id, session_id=edit.session_id,
                instruction=instruction_for(
                    [], regenerate_diagram=True, after=after, slug=edit.slug
                ),
                changes=[], regenerate_diagram=True,
            )
            result = apply_plan(
                client, [redraw], review=review, model_tier=model_tier,
                on_progress=on_progress,
            )
            for o in result:
                o.slug = f"{o.slug} (repair: diagram)"
            outcomes.extend(result)

        for change in missing:
            single = PlannedEdit(
                slug=edit.slug, title=edit.title, audience=edit.audience,
                document_id=edit.document_id, session_id=edit.session_id,
                instruction=instruction_for([change], regenerate_diagram=False, after=after),
                changes=[change],
            )
            result = apply_plan(
                client, [single], review=review, model_tier=model_tier,
                on_progress=on_progress,
            )
            for o in result:
                o.slug = f"{o.slug} (repair: {change.label})"
            outcomes.extend(result)

    return outcomes


# ---------------------------------------------------------------------------
# Reviewers
# ---------------------------------------------------------------------------


def auto_approve(_change: dict[str, Any], _edit: PlannedEdit) -> bool:
    """For unattended runs. Named so it reads as a decision in a script."""
    return True


def make_terminal_reviewer(*, assume_yes: bool = False) -> Reviewer:
    """The delivery manager, at a terminal.

    Shows the before and after for each proposed change and asks. This is the
    human gate; ``--yes`` skips it and the CLI says so out loud when it does.
    """

    def review(change: dict[str, Any], edit: PlannedEdit) -> bool:
        old = _text(change.get("old_html"))
        new = _text(change.get("new_html"))
        print(f"\n  ── {edit.audience}/{edit.slug} · {change.get('operation', 'edit')}")
        if change.get("ai_explanation"):
            print(f"     why: {change['ai_explanation']}")
        if old:
            print(f"     before: {_clip(old)}")
        print(f"     after:  {_clip(new)}")
        if assume_yes:
            print("     → approved (--yes)")
            return True
        answer = input("     approve? [Y/n] ").strip().lower()
        return answer in {"", "y", "yes"}

    return review


def _text(html: Any) -> str:
    import re as _re

    if not html:
        return ""
    return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", str(html))).strip()


def _clip(text: str, width: int = 150) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"
