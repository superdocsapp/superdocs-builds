"""Calendar and mail to a meeting brief pack.

The card says what strong looks like: *the brief is short and specific to that
meeting rather than a generic dossier*. Everything below is arranged around that
one sentence, because it is the whole difficulty. Assembling every document
anyone ever wrote about a supplier is easy and useless — an executive with six
minutes before a call does not want a dossier, they want the four things that
will actually come up.

So the work is mostly **deciding what to leave out**, and that decision is made
here, in code, before a single operation is spent:

1. **Read the invitation.** It is the only source that says what this meeting is
   for — its agenda, its attendees, its date. Everything else is judged against
   it.
2. **Score each candidate source against this meeting.** Agenda keywords, the
   people in the room, and recency. A facilities email about car park
   resurfacing scores zero and never leaves the machine.
3. **Upload only what survived** as read-only attachments. The brief itself is
   the active document; its sources are reference material and cannot be edited
   by the run that reads them.
4. **Draft in one operation**, against a fixed skeleton, with the approval gate
   armed so nothing lands unreviewed.
5. **A human decides on each proposed section**, then the pack is exported.

Selection happening locally is not a shortcut. It is cheaper, it is explainable
— the run prints why each source was kept or dropped — and it means the model is
asked to write about four relevant documents instead of asked to ignore two
irrelevant ones. Asking a model to ignore things is a request it can decline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from render import prepare_for_upload
from superdocs.client import Budget, PendingChange, SuperDocs

# Words that never distinguish one meeting from another, so they must not be
# allowed to make an irrelevant document look relevant.
STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "will", "are", "was",
    "have", "has", "our", "your", "their", "you", "all", "any", "can", "not",
    "meeting", "review", "agenda", "please", "thanks", "regards", "team",
    "email", "sent", "date", "time", "subject", "www", "http", "https",
}


@dataclass
class Meeting:
    """What the invitation says this meeting is."""

    title: str
    when: datetime | None
    location: str
    organiser: str
    attendees: list[tuple[str, str]]  # (name, email)
    agenda: list[str]
    raw: str

    @property
    def domains(self) -> set[str]:
        return {email.split("@")[-1].lower() for _, email in self.attendees if "@" in email}

    @property
    def names(self) -> set[str]:
        return {name.lower() for name, _ in self.attendees if name}

    @property
    def keywords(self) -> set[str]:
        """The terms that make *this* meeting itself.

        Drawn from the title and agenda only — not from the attendee list, so
        that a document merely mentioning a participant does not thereby become
        relevant to the subject.
        """
        text = " ".join([self.title, *self.agenda]).lower()
        return {w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", text) if w not in STOPWORDS}


@dataclass
class Source:
    """A candidate document, and the reasoning about whether it belongs."""

    path: Path
    text: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    selected: bool = False
    uploaded_as: str | None = None  # set when the file had to be converted first

    @property
    def name(self) -> str:
        return self.path.name


# ---------------------------------------------------------------------------
# 1. Read the invitation
# ---------------------------------------------------------------------------


def parse_invite(path: Path) -> Meeting:
    """Parse an .ics invitation.

    Deliberately hand-rolled and narrow: it reads the fields this build uses and
    says so, rather than pulling in a full calendar library to support recurrence
    rules and timezone databases that a meeting brief never touches.
    """
    raw = path.read_text(encoding="utf-8")
    # Unfold RFC 5545 continuation lines before anything else.
    unfolded = re.sub(r"\r?\n[ \t]", "", raw)

    def field_value(name: str) -> str:
        match = re.search(rf"^{name}(?:;[^:]*)?:(.*)$", unfolded, re.MULTILINE)
        return match.group(1).strip() if match else ""

    attendees: list[tuple[str, str]] = []
    for line in re.findall(r"^ATTENDEE.*$", unfolded, re.MULTILINE):
        name = re.search(r"CN=([^;:]+)", line)
        email = re.search(r"mailto:([^\s;]+)", line, re.IGNORECASE)
        if email:
            attendees.append((name.group(1).strip() if name else "", email.group(1).strip()))

    description = field_value("DESCRIPTION").replace("\\n", "\n")
    agenda = [
        re.sub(r"^\s*\d+[.)]\s*", "", line).strip()
        for line in description.splitlines()
        if re.match(r"^\s*\d+[.)]\s+", line)
    ]

    when = None
    stamp = field_value("DTSTART")
    if stamp:
        try:
            when = datetime.strptime(stamp.rstrip("Z"), "%Y%m%dT%H%M%S")
        except ValueError:
            when = None

    organiser = ""
    org_line = re.search(r"^ORGANIZER.*$", unfolded, re.MULTILINE)
    if org_line:
        cn = re.search(r"CN=([^;:]+)", org_line.group(0))
        organiser = cn.group(1).strip() if cn else ""

    return Meeting(
        title=field_value("SUMMARY"),
        when=when,
        location=field_value("LOCATION"),
        organiser=organiser,
        attendees=attendees,
        agenda=agenda,
        raw=raw,
    )


# ---------------------------------------------------------------------------
# 2. Decide what belongs in *this* brief
# ---------------------------------------------------------------------------


def score_source(source: Source, meeting: Meeting, *, today: date) -> Source:
    """Score one candidate against this meeting, and record why.

    Three signals, each of which can be defended to the executive whose time is
    being spent:

    * **Subject overlap** with the agenda and title — the strongest signal, and
      the one that separates "about this meeting" from "about this supplier".
    * **The people in the room** — a thread among the attendees, or with their
      organisation, is more likely to come up than one with strangers.
    * **Recency** — a thread from last week beats one from last year, but only
      as a tie-break. An old contract is not irrelevant merely for being old,
      which is why this weighs least.

    The reasons are kept because a brief that cannot say why something is in it
    cannot be argued with, and an executive who cannot argue with it will stop
    trusting it.
    """
    text = source.text.lower()
    words = set(re.findall(r"[a-z][a-z0-9\-]{2,}", text))

    overlap = meeting.keywords & words
    if overlap:
        source.score += 3.0 * len(overlap) / max(len(meeting.keywords), 1) * 10
        source.reasons.append(
            f"mentions {len(overlap)} of {len(meeting.keywords)} agenda terms: "
            f"{', '.join(sorted(overlap)[:6])}"
        )

    people = {name for name in meeting.names if name and name in text}
    if people:
        source.score += 2.0 * len(people)
        source.reasons.append(f"involves {', '.join(sorted(people))}")

    domains = {d for d in meeting.domains if d in text}
    if domains:
        source.score += 1.5 * len(domains)
        source.reasons.append(f"from or to {', '.join(sorted(domains))}")

    stamps = re.findall(r"\b(20\d\d)-(\d\d)-(\d\d)\b", text)
    stamps += [
        (m[2], {v: k for k, v in enumerate(
            ["jan", "feb", "mar", "apr", "may", "jun",
             "jul", "aug", "sep", "oct", "nov", "dec"], 1)}.get(m[1][:3].lower(), 1), m[0])
        for m in re.findall(r"\b(\d{1,2}) (\w{3,9}) (20\d\d)\b", text)
    ]
    newest: date | None = None
    for y, m, d in stamps:
        try:
            candidate = date(int(y), int(m), int(d))
        except (ValueError, TypeError):
            continue
        if newest is None or candidate > newest:
            newest = candidate
    if newest:
        age_days = (today - newest).days
        if age_days < 400:
            source.score += max(0.0, 2.0 - age_days / 200)
            source.reasons.append(f"most recent date in it is {newest.isoformat()}")

    if not source.reasons:
        source.reasons.append("nothing in it refers to this meeting, its agenda, or its attendees")

    return source


def select_sources(
    paths: list[Path], meeting: Meeting, *, today: date, threshold: float = 6.0
) -> list[Source]:
    """Score every candidate and keep the ones that earn their place.

    The threshold is deliberately a number a human can move, and the run prints
    every score either side of it. A selection you cannot inspect is a selection
    you cannot correct, and the first thing an executive support team will want
    to correct is what the machine decided was worth their principal's time.
    """
    sources = []
    for path in sorted(paths):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            continue
        source = score_source(Source(path=path, text=text), meeting, today=today)
        source.selected = source.score >= threshold
        if not source.selected:
            # Say why it fell short, not merely that it did. "Scored 3.5 against
            # the 6.0 needed" is a sentence an executive support team can argue
            # with and a threshold they can move; "dropped" is not.
            source.reasons.append(
                f"scored {source.score:.1f} against the {threshold:.1f} needed, "
                f"so it was not sent to the model"
            )
        sources.append(source)
    return sources


# ---------------------------------------------------------------------------
# 3–6. Build the pack
# ---------------------------------------------------------------------------

PLACEHOLDER = "To be completed"

SKELETON = """<h1>{title}</h1>
<p><strong>{when}</strong> · {location}</p>
<h2>Why this meeting is happening</h2>
<p>To be completed from the invitation.</p>
<h2>Who is in the room</h2>
<p>To be completed from the invitation.</p>
<h2>Where things stand since last time</h2>
<p>To be completed from the attached sources.</p>
<h2>What needs a decision today</h2>
<p>To be completed from the attached sources.</p>
<h2>What the sources do not tell us</h2>
<p>To be completed from the attached sources.</p>
"""

INSTRUCTION = """You are preparing a pre-meeting brief for {organiser}, who has \
about six minutes to read it before walking into this meeting.

The meeting is: {title}
When: {when}
Agenda:
{agenda}

People in the room:
{people}

Use ONLY the attached source documents. They are the invitation, the email \
threads and the past documents that relate to this meeting.

Fill in each section of the document:

- "Why this meeting is happening" — two sentences at most, from the agenda.
- "Who is in the room" — each attendee, their organisation, and one line on \
what they are likely to want from this meeting, but ONLY where a source \
supports it.
- "Where things stand since last time" — what was agreed previously and what \
has happened since. Name the source document for each point.
- "What needs a decision today" — the specific things that must be resolved in \
this meeting. Be concrete: name the numbers, the dates and the choices.
- "What the sources do not tell us" — anything an attendee might reasonably \
ask about that the attached documents genuinely do not answer.

Before you write "What needs a decision today", check the sources for anything \
time-critical relative to this meeting date of {when}:

- any deadline, notice period or renewal window that has already passed, or \
falls within the next month
- any date that has moved, and whether the sources say a change of that size \
needed anyone's agreement
- any milestone that now falls after a contract or renewal date

If you find one, lead with it. A deadline that has quietly passed is the single \
most useful thing a brief can tell someone before they walk into a room.

Rules that matter more than completeness:

1. Never state anything the attached sources do not support. If you do not \
know, put it under "What the sources do not tell us".
2. Keep it short. This is a brief, not a dossier. If a fact would not change \
how {organiser} behaves in the room, leave it out.
3. Where two sources disagree, say so and give both, rather than choosing.
4. Do not invent names, numbers or dates.
5. Do not repeat the section heading inside the section body. The heading is \
already there; start with the content.
"""


@dataclass
class BriefResult:
    unfilled_sections: list[str]
    draft_attempts: int
    job_status: str
    session_id: str
    meeting: Meeting
    sources: list[Source]
    changes: list[PendingChange]
    approved: list[str]
    rejected: list[str]
    exported: Path | None
    budget: Budget


def build(
    folder: Path,
    *,
    client: SuperDocs,
    session_id: str,
    today: date | None = None,
    approve: bool = False,
    reviewer=None,
    on_note=None,
    model_tier: str = "pro",
    out_dir: Path | None = None,
    export_format: str = "docx",
) -> BriefResult:
    """Assemble one meeting brief pack.

    `approve=False` is the default on purpose: the run stops at the gate with
    the proposed brief pending, because the whole point of the gate is that a
    person decides. `reviewer` is the seam an interface or a test plugs into —
    it receives each proposed change and returns True or False.
    """
    today = today or date.today()

    invite_path = next((p for p in folder.iterdir() if p.suffix.lower() == ".ics"), None)
    if invite_path is None:
        raise FileNotFoundError(
            f"{folder} has no .ics invitation. The invitation is what makes this a "
            f"brief for one meeting rather than a file of everything about a supplier."
        )

    meeting = parse_invite(invite_path)
    candidates = [p for p in folder.iterdir() if p.is_file() and p != invite_path]
    sources = select_sources(candidates, meeting, today=today)
    selected = [s for s in sources if s.selected]

    # Calendar and mail are converted to Markdown first: SuperDocs does not
    # accept .ics or .eml. The rendered copy is what the model reads; the
    # original stays on disk as the thing a human checks the brief against.
    workdir = (out_dir or folder.parent) / ".rendered" / session_id

    # The invitation is always attached: it is the spine of the brief.
    upload_path, _ = prepare_for_upload(invite_path, workdir)
    client.upload_attachment(upload_path, session_id)

    for source in selected:
        upload_path, converted = prepare_for_upload(source.path, workdir)
        source.uploaded_as = upload_path.name if converted else None
        client.upload_attachment(upload_path, session_id)

    when = meeting.when.strftime("%A %d %B %Y, %H:%M") if meeting.when else "date not stated"
    skeleton = SKELETON.format(
        title=meeting.title or "Meeting brief",
        when=when,
        location=meeting.location or "location not stated",
    )

    instruction = INSTRUCTION.format(
        organiser=meeting.organiser or "the chair",
        title=meeting.title,
        when=when,
        agenda="\n".join(f"- {item}" for item in meeting.agenda) or "- not stated in the invitation",
        people="\n".join(f"- {n} <{e}>" for n, e in meeting.attendees) or "- not stated",
    )

    # About one run in three, this turn completes having proposed nothing at
    # all: status `completed`, an empty change list, no error, the document
    # untouched — and the operation still billed. Reported.
    #
    # One retry, because in a human-in-the-loop flow an empty list is genuinely
    # ambiguous: a reviewer cannot tell "nothing needed changing" from "the run
    # silently did nothing", and the second reading is the one that loses a
    # brief. One only — a retry loop against an intermittent fault is how a
    # budget disappears, and the caller is told either way.
    attempts = 0
    while True:
        attempts += 1
        job_id = client.chat_async(
            instruction,
            session_id,
            document_html=skeleton if attempts == 1 else None,
            approval_mode="ask_every_time",
            # `pro`, not the cheaper `core`, and the reason is measured rather
            # than assumed. On this instruction — five sections, five
            # attachments — core completes having proposed nothing about a
            # third of the time, while pro and turbo pause correctly. Same
            # inputs, same session shape, three tiers back to back:
            #
            #   core   completed          0 changes  36.5s
            #   turbo  awaiting_approval  1 change   57.8s
            #   pro    awaiting_approval  4 changes  50.8s
            #
            # A tier costs the same one operation per turn, so the cheaper tier
            # buys nothing here except a brief that sometimes is not written.
            model_tier=model_tier,
        )
        # Not `wait_for_job`: the job announces `awaiting_approval` before it
        # has finished proposing sections, so reading the list too early loses
        # some of them silently. See `wait_for_changes`.
        job = client.wait_for_changes(job_id)
        changes = client.parse_pending_changes(job)

        if changes or attempts >= 2:
            break
        if on_note:
            on_note(
                "the draft turn completed without proposing anything, which is a "
                "known intermittent fault; retrying once"
            )
    approved_ids: list[str] = []
    rejected_ids: list[str] = []

    if changes and (approve or reviewer):
        for change in changes:
            verdict = reviewer(change) if reviewer else True
            client.approve(session_id, job_id, change_id=change.change_id, approved=verdict)
            (approved_ids if verdict else rejected_ids).append(change.change_id)
        job = client.wait_for_job(job_id, what="brief after review")

    # Verify rather than assume — against the artifact, not against a job event.
    #
    # The first version of this check read the document out of the job's
    # `document_sync` events, which carry the state *before* the edits landed.
    # It therefore reported every section as unfilled on a brief that was
    # completely filled: a check that wrongly refuses valid work, which is worse
    # than no check, because it teaches the reader to ignore it.
    #
    # The fix is to ask for the finished document. Exports are free, so
    # verifying against the real artifact costs nothing and tests the thing that
    # actually reaches the executive.
    unfilled: list[str] = []
    if approved_ids:
        try:
            rendered = client.export(session_id=session_id, fmt="markdown")
            text = rendered.decode("utf-8", errors="replace") if isinstance(rendered, bytes) else str(rendered)
            for heading in re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE):
                after = text.split(heading, 1)[1][:400] if heading in text else ""
                if PLACEHOLDER.lower() in after.lower():
                    unfilled.append(heading.strip())
        except Exception as exc:  # noqa: BLE001
            # A failed verification is reported as unknown, never as success.
            if on_note:
                on_note(f"could not verify the finished brief: {exc}")
            unfilled = ["(verification failed — completeness unknown)"]

    exported = None
    if approved_ids and out_dir:
        stamp = meeting.when.date().isoformat() if meeting.when else "undated"
        exported = client.export(
            session_id=session_id,
            fmt=export_format,
            out_path=out_dir / f"brief-{stamp}.{export_format}",
        )

    return BriefResult(
        unfilled_sections=unfilled,
        draft_attempts=attempts,
        job_status=str(job.get("status")),
        session_id=session_id,
        meeting=meeting,
        sources=sources,
        changes=changes,
        approved=approved_ids,
        rejected=rejected_ids,
        exported=exported,
        budget=client.budget,
    )
