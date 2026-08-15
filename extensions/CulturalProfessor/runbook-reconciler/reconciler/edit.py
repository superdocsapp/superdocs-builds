"""Findings into proposed prose, through SuperDocs.

## Why this exists at all, stated honestly

For a threshold, the deterministic layer already knows the answer: the runbook
says `800ms`, the rule says `1.2`, so the replacement is `1.2s` and no model is
needed to work that out. If that were the whole job this file would be a string
substitution and the write-up should say so.

What it is not able to do is the sentence. "Restart the deployment first — it
clears a wedged connection pool without a release" is prose that has to keep
reading like prose after a value inside it moves, and a renamed job in the
middle of an instruction needs the sentence around it to survive. That is the
work here, and it is the reason the passage travels as a *document* with an
instruction rather than as a regex.

## The shape of one request, and what it costs

**One operation per page per sweep, not one per finding.** An operation covers
up to twenty-five sections of targeted edits in a single request, so every
finding on a page is batched into one turn: a passage document holding all of
them, and one instruction naming each. On the headline estimate — 50 PRs a week,
about a tenth of them doc-relevant, about two pages each — that is roughly ten
operations a week for a whole team.

Nothing here runs unless the deterministic layers found something. A sweep over
an estate with no drift never reaches this module, which is rule 5, and it is
asserted in `test_must_never.py` rather than claimed here.

## The four calls, and which one is deliberately not used

`upload`, `chat`, `approve` and a read-back are the spine. The read-back is
`GET /v1/documents/{id}?include_html=true` rather than `export`, because what is
needed at this point is the corrected *text* to splice into Confluence, and
asking for a PDF to extract a sentence from it would be silly. Both are free.
`export` earns its place in `pack.py`, where a real file is the deliverable.

## What a page's instruction may and may not contain

The instruction is built from the **finding** — subject, asserted value,
observed value, evidence path. Page text travels as the document being edited
and never as part of the instruction. That is the structural half of rule 3, and
it is why a page that contains "ignore all previous instructions" cannot reach a
model as an instruction no matter what it says: there is no code path that puts
page prose into the message.
"""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass, field
from typing import Any

from reconciler.claims import Claim, Finding
from reconciler.confluence.splice import diff_range
from reconciler.superdocs import ProposedChange, SuperDocs, SuperDocsError

#: One operation covers up to this many sections. Batching to it is the whole
#: cost model of this project.
SECTIONS_PER_OPERATION = 25

_PASSAGE_HEADING = re.compile(
    r"<h2[^>]*>\s*Passage\s+(?P<n>\d+)\b.*?</h2>(?P<body>.*?)(?=<h2|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TAGS = re.compile(r"<[^>]+>")


@dataclass
class PassageProposal:
    """One finding, and the replacement text SuperDocs came back with."""

    finding_id: str
    subject: str
    #: The anchored value as the page has it: `800ms`.
    original: str
    proposed: str
    #: The whole passage as the page has it. Carried because the read-back
    #: compares a rewritten *passage* against the original one, and diffing the
    #: value against the passage compares two different kinds of thing and
    #: returns the whole sentence.
    original_passage: str = ""
    change_id: str | None = None
    explanation: str = ""


@dataclass
class PageProposal:
    page_id: str
    session_id: str
    job_id: str | None = None
    document_id: str | None = None
    durable_id: str | None = None
    operations: int = 0
    proposals: list[PassageProposal] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def build_passage_document(page_id: str, items: list[tuple[Finding, Claim]]) -> str:
    """The document sent to SuperDocs: only the passages, never the whole page.

    A runbook is long and mostly irrelevant to any one finding. Sending the
    passages alone keeps the request small, keeps the edit confined to text a
    human has already agreed is in scope, and means a page full of macros this
    tool cannot reconstruct never leaves the building.

    Headings are the mapping back. The reply's chunk ids are the service's, and
    matching on them would couple this to an id scheme nobody has promised is
    stable; `Passage 3` is ours and survives a read-back in any format.

    **The heading carries the number and nothing else.** It used to read
    `Passage 1 — alert:PaymentsApiErrorBudgetBurn:threshold`, and against the
    live service that was actively harmful: the model edited the *heading*
    rather than the passage, turning it into `Passage 1 —
    alert:PaymentsApiErrorBudgetBurn:0.05`. Five of seven findings on the first
    live page came back with nothing usable for exactly this reason. A subject
    like `alert:X:threshold` is a machine identifier that reads as prose
    containing the very word the instruction is about, so putting it in the
    document gives the model a plausible wrong thing to correct. It belongs in
    the instruction, which is keyed by passage number anyway.
    """
    parts = [
        f"<h1>Runbook passages to correct (Confluence page {html.escape(page_id)})</h1>",
        "<p>Each passage below is quoted verbatim from an operational runbook. "
        "Correct only what the instruction asks for. Do not edit the headings.</p>",
    ]
    for index, (_finding, claim) in enumerate(items, start=1):
        parts.append(f"<h2>Passage {index}</h2>")
        parts.append(f"<p>{html.escape(claim.excerpt)}</p>")
    return "\n".join(parts)


def build_instruction(items: list[tuple[Finding, Claim]]) -> str:
    """One instruction covering every finding on the page.

    Built entirely from findings. Nothing a page says reaches this string except
    the value being replaced, which is quoted as a value rather than
    interpolated as prose — see the module docstring on rule 3.
    """
    lines = [
        "Each passage below contains one factual error, listed here. For each, make the "
        "smallest edit that corrects the fact and leaves the sentence reading naturally. "
        "Do not restructure the passage, do not add commentary, and do not change anything "
        "not listed.",
        "",
        # Both of these rules exist because the live service broke them and the
        # wrong text reached a real page. See `_sane`, which refuses the results
        # rather than trusting the instruction to be followed.
        "Two rules about the replacement itself:",
        "1. Keep the unit and format the document already uses. If the text says '750ms' "
        "and the infrastructure value is given as '1.2' seconds, the replacement is '1.2s' "
        "-- never a bare number that leaves the sentence saying 'above 1.2 for 10 minutes'.",
        "2. Where the infrastructure text lists several valid names, choose exactly the one "
        "that belongs here and write only that. Never paste the list: 'Page the "
        "Fulfilment, Payments Core, Tracking rota' is not a sentence.",
        "",
    ]
    for index, (finding, claim) in enumerate(items, start=1):
        lines.append(
            f"Passage {index}: the text says {claim.asserted!r}. "
            f"The infrastructure says {finding.observed!r} "
            f"(source: {finding.evidence_file}:{finding.evidence_line or 1}). "
            f"Replace the value and adjust the wording only as far as the sentence needs."
        )
    return "\n".join(lines)


def propose_for_page(
    client: SuperDocs,
    page_id: str,
    items: list[tuple[Finding, Claim]],
    model_tier: str | None = None,
) -> PageProposal:
    """One page, one operation, every finding on it.

    Returns proposals without approving anything. The SuperDocs job is left
    parked at `awaiting_approval`, which holds that session — a second turn
    against it comes back `409 session_busy`. That is deliberate: the human gate
    decides, and `apply_proposal` below is what answers the parked job with
    those decisions. A session per page keeps one page's parked batch from
    blocking another's.
    """
    editable = [
        (finding, claim)
        for finding, claim in items
        if claim.anchor.editable and finding.verdict == "contradicts"
    ]
    proposal = PageProposal(page_id=page_id, session_id="")
    for finding, claim in items:
        if (finding, claim) not in editable:
            proposal.skipped.append(
                (finding.finding_id, claim.anchor.refusal or "not an editable contradiction")
            )
    if not editable:
        return proposal

    if len(editable) > SECTIONS_PER_OPERATION:
        # Splitting would be a second operation and a second parked session, so
        # the caller is told rather than being quietly charged twice.
        raise SuperDocsError(
            f"page {page_id} has {len(editable)} findings and one operation covers "
            f"{SECTIONS_PER_OPERATION} sections. Split the sweep."
        )

    proposal.session_id = client.init_session()
    document = build_passage_document(page_id, editable)
    proposal.document_id = client.upload(
        filename=f"runbook-{page_id}-passages.html",
        content=document,
        session_id=proposal.session_id,
        open_mode="new_focused",
    )
    # The durable id, not the session-scoped one, is what reopens the document
    # for the read-back. `upload` returns only `doc_…`.
    proposal.durable_id = _durable_id(client, proposal.session_id, proposal.document_id)

    # ASYNC, and this is not a performance choice -- it is the only path whose
    # changes can be approved.
    #
    # Verified against the live service on 2026-08-15. A synchronous `/v1/chat`
    # turn returns `document_changes.requires_approval: true` and a list of
    # `change_id`s, and carries **no job id at all**. `/v1/chat/{s}/approve`
    # requires one (`422` without the field, `404 Job not found` when empty),
    # and the job the sync turn did create is `job_type: sync_chat`, status
    # `completed`, which approve rejects with `400 Job is not awaiting
    # approval`. So a sync turn proposes changes that nothing can ever accept:
    # the operation is spent, the wording comes back, and the document is never
    # updated. The stub had modelled the sync reply as carrying a job id, which
    # is why every offline test passed against a path that cannot work.
    proposal.job_id = client.chat_async(
        message=build_instruction(editable),
        session_id=proposal.session_id,
        document_id=proposal.document_id,
        model_tier=model_tier,
    )
    proposal.operations = 1
    job = client.wait_for_job(proposal.job_id)

    changes = client.pending_changes(job)
    proposal.proposals = _map_changes(changes, editable)
    return proposal


def _durable_id(client: SuperDocs, session_id: str, document_id: str | None) -> str | None:
    """The uuid under the `doc_…`, or None if it cannot be resolved.

    Never fatal: the read-back is a belt-and-braces check, and losing it is a
    reason to trust the reply instead, not to fail a page that was worded fine.
    """
    try:
        for entry in client.documents(session_id):
            if not document_id or entry.get("document_id") == document_id:
                durable = entry.get("durable_document_id")
                if durable:
                    return str(durable)
    except SuperDocsError:
        return None
    return None


def propose_all(register: Any, client: SuperDocs, model_tier: str | None = None) -> dict[str, int]:
    """A proposal for every page holding undecided, editable contradictions.

    The only place in this project that spends anything, and it is entered only
    with findings the deterministic layers produced. A page whose findings are
    all comment-only never opens a session; an estate with no drift never
    reaches this function at all.

    Findings that already carry a proposal are skipped, which is what makes this
    safe to re-run after a crash: the register is the record of what has been
    paid for.
    """
    queue = [f for f in register.review_queue() if not f.proposed and f.page_id]
    by_page: dict[str, list[tuple[Finding, Claim]]] = {}
    for finding in queue:
        claim = register.claim(finding.claim_id or "")
        if claim is None:
            continue
        by_page.setdefault(finding.page_id, []).append((finding, claim))

    spent = 0
    pages = 0
    for page_id, items in sorted(by_page.items()):
        proposal = propose_for_page(client, page_id, items, model_tier=model_tier)
        spent += proposal.operations
        if proposal.operations:
            pages += 1
        for item in proposal.proposals:
            register.record_proposal(
                finding_id=item.finding_id,
                page_id=page_id,
                session_id=proposal.session_id,
                job_id=proposal.job_id,
                document_id=proposal.document_id,
                durable_id=proposal.durable_id,
                change_id=item.change_id,
                proposed=item.proposed,
                explanation=item.explanation,
            )
    return {"operations": spent, "pages": pages, "proposals": len(queue)}


def _map_changes(
    changes: list[ProposedChange], items: list[tuple[Finding, Claim]]
) -> list[PassageProposal]:
    """Match each proposed change back to the finding it answers.

    **By content, never by position.** Matching on order would work until the
    first time the service returns changes in a different order, or skips a
    passage it judged already correct — both perfectly reasonable things for it
    to do — and the failure mode is silently splicing passage two's replacement
    into passage one. An unmatched change is dropped and the finding escalates,
    which is the outcome a human can see.
    """
    out: list[PassageProposal] = []
    used: set[str] = set()

    for index, (finding, claim) in enumerate(items, start=1):
        match = _change_for(changes, index, claim, used)
        if match is None:
            continue
        used.add(match.change_id)
        proposed = _replacement(
            old_text=_text_of(match.old_html) or claim.excerpt,
            new_text=_text_of(match.new_html),
            asserted=claim.asserted,
        )
        if not proposed:
            continue
        out.append(
            PassageProposal(
                finding_id=finding.finding_id,
                subject=finding.subject,
                original=claim.asserted,
                proposed=proposed,
                original_passage=claim.excerpt,
                change_id=match.change_id,
                explanation=match.explanation,
            )
        )
    return out


def _change_for(
    changes: list[ProposedChange], index: int, claim: Claim, used: set[str]
) -> ProposedChange | None:
    """The change that is about this passage, on evidence.

    In order of how much it proves: the passage's own text, then the marker this
    module wrote into the heading, then the exact value being corrected. If none
    of the three match, nothing is returned.
    """
    excerpt = claim.excerpt.strip()
    marker = f"Passage {index}"
    candidates = [c for c in changes if c.change_id not in used]

    for test in (
        lambda c: bool(excerpt) and excerpt in _text_of(c.old_html),
        lambda c: marker in c.old_html or marker in c.new_html,
        lambda c: claim.asserted in _text_of(c.old_html),
    ):
        for change in candidates:
            if test(change):
                return change
    return None


def _text_of(fragment: str) -> str:
    return html.unescape(_TAGS.sub("", fragment)).strip()


def _replacement(old_text: str, new_text: str, asserted: str) -> str:
    """What the anchored value became, derived by diff rather than expectation.

    The anchor covers `800ms` exactly, so what gets spliced into Confluence has
    to be what `800ms` became — not the rewritten sentence, which would put a
    paragraph in the middle of a line.

    An earlier version searched the new text for the *observed* ground-truth
    value, which works for a threshold and not at all for the interesting cases:
    when a runbook names a CI job that no longer exists, the observed value is
    "no job called that; the declared jobs are …", and the replacement is
    something the model chose. Diffing the passage against itself needs no
    expectation and handles both.

    Returns empty when the model changed something other than the anchored
    value. The caller escalates, and a finding a human looks at beats a
    paragraph written into the middle of a sentence.
    """
    if not new_text or new_text == old_text:
        return ""
    change = diff_range(old_text, new_text)
    if change is None:
        return ""

    # The anchored value may be several words -- `7 days`, `4 hours`, `03:00 UTC
    # daily` -- while the edit inside it touches one. When the whole changed
    # range sits inside the occurrence of `asserted`, the replacement is simply
    # whatever now occupies that span, and no token arithmetic is needed.
    #
    # Found live on 2026-08-15: the service correctly returned "Automated backup
    # retention: 7 days" -> "... 14 days" and this function threw it away. The
    # token logic below widened the diff to `7`, `asserted` was `7 days`, so the
    # `asserted not in old_token` guard rejected a perfectly good change. The
    # finding then escalated as "no replacement text was produced" -- a silent
    # quality loss that looks like the model declining rather than like a bug
    # here, which is exactly why it survived the offline tests.
    at = old_text.find(asserted)
    if at != -1 and at <= change.start and change.end_old <= at + len(asserted):
        tail = len(old_text) - (at + len(asserted))
        return _sane(new_text[at : len(new_text) - tail if tail else None].strip(), asserted)

    left = _token_start(old_text, change.start)
    old_token = old_text[left : _token_end(old_text, change.end_old)]
    new_token = new_text[left : _token_end(new_text, change.end_new)]

    if asserted not in old_token:
        # The model edited something this finding did not ask about. Not
        # necessarily wrong -- but not something to apply under this anchor.
        return ""
    if old_token == asserted:
        return _sane(new_token, asserted)

    # The changed token is larger than the value: `800ms,` becoming `1.2s,`.
    # Strip the shared surroundings so what comes back fits the anchor exactly.
    prefix, _, suffix = old_token.partition(asserted)
    if new_token.startswith(prefix) and new_token.endswith(suffix):
        inner = new_token[len(prefix) : len(new_token) - len(suffix) or None]
        return _sane(inner, asserted)
    return ""


#: `750ms`, `1.2s`, `5%`, `7 days` -- a number carrying a unit.
_NUMBER_WITH_UNIT = re.compile(r"^\d[\d.,]*\s*[A-Za-z%]+$")
#: `1.2`, `14`, `0.05` -- a number with no unit at all.
_BARE_NUMBER = re.compile(r"^\d[\d.,]*$")


def _sane(replacement: str, asserted: str) -> str:
    """A value of the same shape as the one it replaces, or nothing.

    The instruction tells the service not to add commentary, to keep the
    document's unit, and to pick one name rather than pasting a list. It mostly
    complies. Mostly is not a control, and every rule below is here because a
    live run broke it — the first two after the wrong text had already reached a
    real page:

        '750ms'             -> '1.2'
            The estate stores the threshold as a bare `1.2` and the model copied
            it, leaving the page reading "latency stays above 1.2 for 10
            minutes". Shorter than the original, no commentary, and meaningless.

        'Payments Platform' -> 'Fulfilment, Payments Core, Tracking'
            The observed value is a sentence naming every declared rota, so the
            model pasted all three: "Page the Fulfilment, Payments Core,
            Tracking rota". One value became a list.

        'Payments Platform' -> 'Payments Platform is not a valid rota; valid
                                rotas are Fulfilment, Payments Core and Tracking.'
        'rollback-production' -> "rollback-production (Note: ... not a valid CI
                                job; please use one of the declared jobs: ...)"
            Commentary appended rather than a replacement made.

    The through-line: a replacement has to have the same *shape* as what it
    replaces. Same units, same number of items, roughly the same size, and not
    containing the thing it was supposed to replace. None of these can tell a
    right value from a wrong one — only that this is not a value at all.

    Refusing costs a human one look at an escalated finding. Accepting costs
    wrong prose in an operational instruction that somebody follows at 3am.
    """
    if not replacement:
        return ""

    # Commentary appended rather than a replacement made.
    if asserted in replacement and len(replacement) > len(asserted):
        return ""
    if len(replacement) > 3 * len(asserted) + 20:
        return ""

    # The unit the document was using has been dropped.
    if _NUMBER_WITH_UNIT.match(asserted.strip()) and _BARE_NUMBER.match(replacement.strip()):
        return ""

    # One value became a list. Counting separators rather than looking for
    # specific words keeps this working for jobs, rotas, regions and anything
    # else whose "observed" value happens to enumerate the valid options.
    if replacement.count(",") > asserted.count(","):
        return ""

    return replacement


def _token_start(text: str, index: int) -> int:
    while index > 0 and not text[index - 1].isspace():
        index -= 1
    return index


def _token_end(text: str, index: int) -> int:
    while index < len(text) and not text[index].isspace():
        index += 1
    return index


def apply_proposal(
    client: SuperDocs,
    proposal: PageProposal,
    decisions: dict[str, bool],
) -> dict[str, str]:
    """Answer the parked batch with the human's decisions, then read it back.

    `decisions` is keyed by finding id, which is what the review gate speaks;
    it is translated to change ids here so nothing above this layer has to know
    SuperDocs exists.

    The read-back is not ceremony. It is the difference between "the service
    said it applied the change" and "the stored document contains it", and those
    disagreed with each other often enough during the sibling build to be worth
    one free call.
    """
    if not proposal.job_id:
        return {}
    by_change = {
        item.change_id: decisions.get(item.finding_id, False)
        for item in proposal.proposals
        if item.change_id
    }
    client.approve(
        session_id=proposal.session_id,
        job_id=proposal.job_id,
        decisions=by_change,
        approved_by_default=False,
    )

    if not proposal.durable_id:
        return {
            item.finding_id: item.proposed
            for item in proposal.proposals
            if decisions.get(item.finding_id)
        }

    stored = _stored_after_approval(client, proposal)
    passages = read_back_passages(stored)
    out: dict[str, str] = {}
    for index, item in enumerate(proposal.proposals, start=1):
        if not decisions.get(item.finding_id):
            continue
        text = passages.get(index, "")
        # The stored document is what the service really holds, which has
        # disagreed with the reply it just sent often enough to be worth one
        # free call. When the read-back cannot be parsed the proposal stands.
        from_stored = (
            _replacement(item.original_passage, text, item.original)
            if text and item.original_passage
            else ""
        )
        out[item.finding_id] = from_stored or item.proposed
    return out


def _stored_after_approval(
    client: SuperDocs,
    proposal: PageProposal,
    attempts: int = 6,
    pause: float = 2.0,
) -> str:
    """The stored document, once it has caught up with the approval.

    `approve` answers `{"status": "ok", "batch_complete": true}` roughly three
    seconds before `GET /v1/documents/{id}?include_html=true` reflects it —
    measured live on 2026-08-15: the read immediately after the approval
    returned the *old* text, and the same read three seconds later returned the
    new one. A single read-back therefore reports "the service said it applied
    the change but the stored document does not contain it", which is the exact
    sentence this read-back exists to be able to say truthfully. It has to mean
    a real disagreement, not a race the caller lost.

    So: poll until the stored text stops matching what was there before, or
    give up and let the caller fall back to the reply. Bounded, because waiting
    for ever on a document that genuinely did not change is worse than
    proceeding on the wording the service already returned.
    """
    stale = {item.original_passage.strip() for item in proposal.proposals if item.original_passage}
    stored = ""
    for attempt in range(attempts):
        stored = client.document_html(proposal.durable_id or "")
        passages = read_back_passages(stored)
        text = " ".join(passages.values())
        if text and not any(old and old in text for old in stale):
            return stored
        if attempt < attempts - 1:
            time.sleep(pause)
    return stored


def read_back_passages(stored_html: str) -> dict[int, str]:
    """The corrected passages, by the number this module gave them."""
    return {
        int(match.group("n")): _text_of(match.group("body"))
        for match in _PASSAGE_HEADING.finditer(stored_html)
    }


def deny(client: SuperDocs, proposal: PageProposal) -> None:
    """Throw a parked batch away. Free, and it releases the session.

    Called when a human rejects everything on a page, and on cleanup after a
    crash. A parked job left behind is not a leak of money — denials cost
    nothing — but it is a session that answers `409 session_busy` forever, which
    is worse to diagnose than it is to prevent.
    """
    if not proposal.job_id:
        return
    try:
        client.approve(
            session_id=proposal.session_id,
            job_id=proposal.job_id,
            decisions={item.change_id: False for item in proposal.proposals if item.change_id},
            approved_by_default=False,
        )
    except Exception:
        # Deliberately bare, and this is the one place in the project it is
        # right: cleanup must never be the thing that fails a run. A network
        # that dropped, a service that is down, a session already settled by
        # somebody else — none of it should turn "the human rejected these"
        # into a traceback. The parked job stays in the register and `rr status`
        # is where somebody deals with it.
        return


__all__ = [
    "SECTIONS_PER_OPERATION",
    "PageProposal",
    "PassageProposal",
    "apply_proposal",
    "build_instruction",
    "build_passage_document",
    "deny",
    "propose_all",
    "propose_for_page",
    "read_back_passages",
]
