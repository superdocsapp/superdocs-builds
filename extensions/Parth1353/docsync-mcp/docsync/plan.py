"""Planning — decide what to say to which document, before spending anything.

This is the part worth reading. Everything here is offline, deterministic and
free: it needs no API key and makes no call, which is what lets ``docsync
plan`` run on every save in an editor without costing an operation.

Three decisions happen here.

**Which facts moved.** A comparison of two rendered fact tables. Rendered, not
raw, because ``30`` and ``30.0`` are the same timeout and must not produce six
document edits that change nothing.

**Which documents carry them.** Computed from the coverage each document
declares, never from a search of the whole docs tree. The set of documents
deliberately *not* contacted is returned alongside, because "what did you
leave alone" is half of the claim this tool makes.

**Whether the edit is safe to phrase as a substitution.** This is the part
Task 2 of this round got wrong live and paid for. An instruction of the form
"replace X with Y" is only honest if X is actually in the document, exactly
once, unambiguously. So every document is read *first* and each fact is
classified against it:

``literal``    the old value is in the text and can be quoted verbatim
``weak``       it is there, but it is short and repeats — anchor on the label
``unanchored`` it is not there at all: either the document states it in prose
               ("up to five attempts") or the coverage declaration is wrong,
               and from outside those two are indistinguishable
``current``    the document already says the new value; there is nothing to do

Only ``literal`` and ``weak`` edits are verifiable afterwards. ``unanchored``
ones are held back unless you ask for them, and are never reported as verified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docsync.facts import FactTable
from docsync.registry import DocumentSpec, Registry

# ---------------------------------------------------------------------------
# What moved
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactChange:
    key: str
    label: str
    is_list: bool
    before_text: str | list[str]
    after_text: str | list[str]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def before_display(self) -> str:
        return _display(self.before_text)

    @property
    def after_display(self) -> str:
        return _display(self.after_text)


def _display(value: str | list[str]) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return value


def diff_tables(before: FactTable, after: FactTable) -> list[FactChange]:
    """Every fact whose rendered value moved, in registry order.

    Facts that could not be read on either side are not changes — they are
    reported separately by ``build_plan`` and they stop the run. A fact that
    went from readable to unreadable is the single most dangerous thing this
    tool can encounter, because the "new value" is unknown: writing anything
    into a document at that point is a guess. It never guesses.
    """
    changes: list[FactChange] = []
    for key, after_value in after.values.items():
        before_value = before.values.get(key)
        if before_value is None or not before_value.ok or not after_value.ok:
            continue
        if before_value.text == after_value.text:
            continue
        added: tuple[str, ...] = ()
        removed: tuple[str, ...] = ()
        if after_value.is_list:
            old = set(before_value.text or [])
            new = set(after_value.text or [])
            added = tuple(sorted(new - old))
            removed = tuple(sorted(old - new))
            if not added and not removed:
                continue
        changes.append(
            FactChange(
                key=key,
                label=after_value.label,
                is_list=bool(after_value.is_list),
                before_text=before_value.text or ("" if not after_value.is_list else []),
                after_text=after_value.text or ("" if not after_value.is_list else []),
                added=added,
                removed=removed,
            )
        )
    return changes


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

ANCHOR_LITERAL = "literal"
ANCHOR_WEAK = "weak"
ANCHOR_UNANCHORED = "unanchored"
ANCHOR_CURRENT = "current"

_FRONT_MATTER = re.compile(r"\A﻿?---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_HTML_BLOCK = re.compile(r"<!--\s*docsync:\s*\r?\n.*?-->", re.S)


def split_front_matter(text: str) -> tuple[str, str]:
    """``(front matter including its fences, the rest)``.

    The front matter is held back from SuperDocs entirely: it is stripped
    before upload and re-attached on write-back. Two reasons, and the second is
    the important one.

    It is machinery, not prose — a coverage list naming fact keys — so a model
    asked to update a retry count has no business seeing it. And an instruction
    that says "do not touch the front matter" is a request, whereas not sending
    it is a guarantee. The cheapest way to stop an edit reaching something is
    not to show it.
    """
    match = _FRONT_MATTER.match(text)
    if not match:
        return "", text
    return match.group(0), text[match.end() :]


def body_of(text: str) -> str:
    """The prose, without the machinery.

    Coverage declarations name fact *keys* and sometimes values, and counting
    them as occurrences would let a document appear to contain an anchor it
    does not contain. List and section numbering is removed for the same
    reason — see ``mask_structure``.
    """
    return mask_structure(_HTML_BLOCK.sub("", split_front_matter(text)[1]))


def occurrences(haystack: str, needle: str) -> int:
    """How many times a value appears, respecting token boundaries.

    Plain ``in`` is not good enough here. A timeout of ``30`` is "in" the
    string ``300`` and in ``1.30``, and an instruction built on either would
    tell a model to rewrite a number it was never asked about.

    Getting the dot right is the fiddly part, and the first version of this
    got it wrong in the direction that matters. Treating ``.`` as part of the
    token stops ``30`` matching inside ``30.5`` — but it also stops ``30
    seconds`` matching in *"the call is given 30 seconds."*, because a full
    stop ends most sentences that state a value. The result was a document
    that plainly contained its anchor being classified as prose-only, which
    silently demotes a verifiable edit into an unverifiable one. So the rule
    is narrower: a dot only joins the token when a digit is on the other side
    of it, which is what makes it a decimal rather than punctuation.

    A second shape needs the same care and is easier to miss, because it is
    not numeric: ``POST /v1/circuits`` is a substring of
    ``POST /v1/circuits/{id}/provision``. Left alone, a route removed from the
    code would verify as *successfully removed* while its longer sibling still
    sat in the table. So ``/`` and ``-`` join a token too — they continue a
    path or an identifier, while a bracket, a pipe, a comma or a full stop end
    one.
    """
    if not needle:
        return 0
    # Applied on both ends unconditionally rather than only for alphanumeric
    # edges: a value can perfectly well end in `}` or `%` and still be the
    # prefix of something longer.
    pattern = r"(?<![\w/-])(?<!\d\.)" + re.escape(needle) + r"(?![\w/-])(?!\.\d)"
    return len(re.findall(pattern, haystack))


_ORDERED_MARKER = re.compile(r"^([ \t]*(?:#{1,6}[ \t]+)?)(\d+)(?=[.)][ \t])", re.M)


def mask_structure(text: str) -> str:
    """Blank out numbers that are document structure rather than content.

    A runbook whose third check reads ``3. **Has it dead-lettered?**`` contains
    the digit ``3`` exactly once — and it is a list marker, not the retry
    limit. Anchoring on it looks like a clean single-occurrence match and would
    send an instruction whose most obvious reading is *renumber this list*.

    Found by running the example rather than by thinking about it, which is
    the only way this kind of thing turns up. Section numbers in headings go
    the same way for the same reason.

    Fenced code is deliberately *not* masked. A document that quotes
    ``MAX_ATTEMPTS = 3`` in a code sample is a document that genuinely goes
    stale when the constant moves, and updating it is the whole job.
    """
    return _ORDERED_MARKER.sub(lambda m: m.group(1) + " " * len(m.group(2)), text)


def _is_short(text: str) -> bool:
    """Short enough that repetition makes it a bad thing to quote.

    Kept only for the audit's advice about tightening a fact with a
    ``format:``. It is deliberately **not** what decides whether an
    instruction may say "change all of them" — see ``classify``.
    """
    return len(text) <= 4


@dataclass(frozen=True)
class Anchor:
    key: str
    kind: str
    count: int = 0
    note: str = ""

    @property
    def sendable(self) -> bool:
        return self.kind in (ANCHOR_LITERAL, ANCHOR_WEAK)


def classify(
    change: FactChange, body: str, *, siblings: dict[str, tuple[str, str]] | None = None
) -> Anchor:
    """Where a change sits relative to one document's text.

    ``siblings`` maps every *other* fact this document covers to the value it
    currently has, changed or not. It is what stops the worst bug this build
    has produced.

    On a live run the runbook covered both the retry backoff (30 seconds) and
    the carrier request timeout (also 30 seconds). Only the backoff changed.
    The instruction said, correctly by its own lights, *"wherever this document
    says 30 seconds as the retry backoff interval, replace it with 45 seconds —
    there may be more than one occurrence, change all of them"*. The model did
    exactly that, to both sentences, and the runbook then told an on-call
    engineer that the carrier call timeout was 45 seconds when the code said
    30. Verification passed, because "45 seconds" was indeed present.

    The old rule only compared *changed* facts against each other, so a
    collision with an unchanged fact was invisible. The rule now is simpler and
    much harder to get wrong: **an anchor that appears more than once anywhere
    in the document is ambiguous**, full stop, and an ambiguous anchor never
    gets an instruction containing the words "change all of them". It gets the
    labelled-sentence phrasing instead.
    """
    if change.is_list:
        missing_additions = [item for item in change.added if occurrences(body, item) == 0]
        lingering_removals = [item for item in change.removed if occurrences(body, item) > 0]
        if not missing_additions and not lingering_removals:
            return Anchor(change.key, ANCHOR_CURRENT, note="the list already matches the code")
        return Anchor(
            change.key,
            ANCHOR_LITERAL,
            count=len(missing_additions) + len(lingering_removals),
            note=f"{len(missing_additions)} to add, {len(lingering_removals)} to remove",
        )

    before = str(change.before_text)
    after = str(change.after_text)
    before_hits = occurrences(body, before)
    after_hits = occurrences(body, after)

    # How many occurrences of the old text belong to *other* facts that
    # legitimately still read that way.
    sibling_matches = sum(
        1
        for key, (_label, value) in (siblings or {}).items()
        if key != change.key and value == before
    )

    if after_hits > 0 and before_hits <= sibling_matches:
        # Already applied. The naive test — "the old value is gone" — is wrong
        # whenever another fact in the same document happens to share it. The
        # runbook states a retry backoff and a request timeout that both read
        # "30 seconds"; once the backoff moves to 45, one "30 seconds" is still
        # there and it belongs to the timeout. Reading that as "not yet
        # applied" made a live run re-send the same edit every round, verify it
        # (the new value *was* present), and burn an operation a round until
        # the no-progress guard stopped it.
        return Anchor(
            change.key,
            ANCHOR_CURRENT,
            count=after_hits,
            note="the document already states the new value"
            + (
                "; the old value still present belongs to another fact"
                if sibling_matches
                else ""
            ),
        )
    if before_hits == 0:
        return Anchor(
            change.key,
            ANCHOR_UNANCHORED,
            note="the old value does not appear literally — the document may state it "
            "in prose, or the coverage declaration may be wrong",
        )

    clash = sorted(
        label
        for key, (label, value) in (siblings or {}).items()
        if key != change.key and value == before
    )
    if clash:
        return Anchor(
            change.key,
            ANCHOR_WEAK,
            count=before_hits,
            note=f'"{before}" is also the current value of {", ".join(clash)} in this '
            f"document, which is not changing; the instruction will name the sentence "
            f"rather than the value",
        )
    if before_hits > 1:
        return Anchor(
            change.key,
            ANCHOR_WEAK,
            count=before_hits,
            note=f'"{before}" appears {before_hits} times, and there is no way to know '
            f"from outside that every occurrence means the same thing; the instruction "
            f"will name the sentence rather than ask for all of them",
        )
    return Anchor(change.key, ANCHOR_LITERAL, count=before_hits)


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass
class DocumentPlan:
    path: str
    title: str
    changes: list[FactChange]
    anchors: dict[str, Anchor]
    needs_upload: bool = True
    instruction: str = ""
    to_send: list[FactChange] = field(default_factory=list)
    #: Facts this document carries that are **not** changing, and whose current
    #: value is literally present. After the edit they must all still be there.
    #: This is the check that catches collateral damage — an edit that lands
    #: the value it was asked for and quietly rewrites a neighbouring sentence
    #: that happened to read the same. Verifying only what changed cannot see
    #: it; a live run proved that the hard way.
    invariants: list[dict[str, str]] = field(default_factory=list)
    rounds_needed: int = 0

    @property
    def sendable(self) -> list[FactChange]:
        return [c for c in self.changes if self.anchors[c.key].sendable]

    @property
    def unanchored(self) -> list[FactChange]:
        return [c for c in self.changes if self.anchors[c.key].kind == ANCHOR_UNANCHORED]

    @property
    def current(self) -> list[FactChange]:
        return [c for c in self.changes if self.anchors[c.key].kind == ANCHOR_CURRENT]

    @property
    def verifiable(self) -> list[FactChange]:
        """This round's changes whose landing can be checked afterwards.

        Deliberately *not* every change that was sent. An unanchored change is
        applied to prose, and prose has no value to search for afterwards — so
        it is reported as "applied, not verified" and never counted towards a
        green result.
        """
        return [c for c in self.this_round if self.anchors[c.key].sendable]

    @property
    def this_round(self) -> list[FactChange]:
        """At most one change per document per round, and this is measured.

        A turn carrying one instruction item is reliable. A turn carrying two
        is not: on the example ADR, one-item turns paused at the approval gate
        12 times out of 12, while two-item turns paused once out of seven — the
        other six ran to ``completed``, proposed nothing, persisted nothing and
        replied "✅ I've completed the requested change". A three-item turn
        paused but applied one of the three. Task 2 of this round measured the
        same shape independently: a four-field turn applies some fields and
        quietly skips others.

        Sending the changes one at a time is the fix. Splitting them across
        sessions instead would be cheaper to code and wrong — each session
        holds its own copy of the document, so the edits would land on
        different copies and no single copy would ever be correct. So a
        document with three changed facts takes three rounds against one
        session, and each round is a real gate with real diffs.
        """
        return self.to_send[:1]

    @property
    def remaining(self) -> list[FactChange]:
        return self.to_send[1:]

    @property
    def operations(self) -> int:
        if not self.this_round:
            return 0
        return (1 if self.needs_upload else 0) + 1


@dataclass
class ChangePlan:
    registry_root: Path
    before_origin: str
    after_origin: str
    changes: list[FactChange] = field(default_factory=list)
    documents: list[DocumentPlan] = field(default_factory=list)
    untouched: list[str] = field(default_factory=list)
    already_current: list[str] = field(default_factory=list)
    unresolved: dict[str, str] = field(default_factory=dict)
    baseline_gaps: dict[str, str] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    allow_prose: bool = False

    @property
    def operations(self) -> int:
        return sum(doc.operations for doc in self.documents)

    @property
    def blocked(self) -> bool:
        """A fact that cannot be read at head stops everything.

        Not a warning. If ``retry.py`` was refactored so ``MAX_ATTEMPTS`` no
        longer exists, the correct new sentence for the runbook is a judgement
        a person has to make, and every automated option — leave it, guess it,
        delete it — is worse than stopping and saying so.
        """
        return bool(self.unresolved)

    @property
    def rounds(self) -> int:
        """How many apply rounds it takes to land everything."""
        return max((len(d.to_send) for d in self.documents), default=0)

    @property
    def unanchored_total(self) -> int:
        return sum(len(doc.unanchored) for doc in self.documents)


def build_plan(
    registry: Registry,
    before: FactTable,
    after: FactTable,
    *,
    documents: list[DocumentSpec] | None = None,
    uploaded: dict[str, str] | None = None,
    doc_text: dict[str, str] | None = None,
    allow_prose: bool = False,
) -> ChangePlan:
    """Everything ``apply`` will do, decided before anything is sent.

    ``uploaded`` maps a document path to the content hash SuperDocs already
    holds; a document whose hash still matches does not need re-uploading and
    the plan's cost drops by one operation for it.
    """
    documents = registry.documents() if documents is None else documents
    uploaded = uploaded or {}
    changes = diff_tables(before, after)

    plan = ChangePlan(
        registry_root=registry.root,
        before_origin=before.origin,
        after_origin=after.origin,
        changes=changes,
        unresolved=dict(after.errors),
        baseline_gaps=dict(before.errors),
        uncovered=registry.uncovered_facts(),
        allow_prose=allow_prose,
    )

    changed_keys = {c.key for c in changes}
    by_key = {c.key: c for c in changes}

    for spec in documents:
        relevant = [by_key[k] for k in spec.covers if k in changed_keys]
        if not relevant:
            plan.untouched.append(spec.path)
            continue

        text = (
            doc_text.get(spec.path)
            if doc_text is not None
            else _read(registry.resolve(spec.path))
        )
        if text is None:
            plan.unresolved[spec.path] = "the document could not be read from disk"
            continue
        body = body_of(text)

        # What every fact this document covers reads as *right now* — before
        # anything is edited. Used to spot an anchor that is also some other
        # fact's current value, which is the collision that produced a wrong
        # runbook on a live run.
        siblings: dict[str, tuple[str, str]] = {}
        for key in spec.covers:
            value = before.values.get(key) or after.values.get(key)
            if value is not None and value.ok and isinstance(value.text, str):
                siblings[key] = (value.label, value.text)

        anchors = {c.key: classify(c, body, siblings=siblings) for c in relevant}
        doc_plan = DocumentPlan(
            path=spec.path,
            title=spec.title,
            changes=relevant,
            anchors=anchors,
            needs_upload=uploaded.get(spec.path) != content_hash(text),
            invariants=[
                {"key": key, "label": label, "value": value}
                for key, (label, value) in sorted(siblings.items())
                if key not in {c.key for c in relevant} and occurrences(body, value) > 0
            ],
        )
        # Order matters: the anchored substitutions are numbered first so the
        # instruction reads as a list of exact edits with the fuzzy ones at the
        # end, rather than opening with the vaguest item.
        doc_plan.to_send = list(doc_plan.sendable) + (
            list(doc_plan.unanchored) if allow_prose else []
        )

        if not doc_plan.to_send:
            # Nothing to send means nothing to upload either — a document whose
            # every changed fact is already correct must cost zero, or running
            # this tool twice in a row would bill for the second run.
            doc_plan.needs_upload = False
            if doc_plan.unanchored:
                # Held back rather than skipped: these need either --allow-prose
                # or a human, and the report must say so out loud.
                plan.documents.append(doc_plan)
            else:
                plan.already_current.append(spec.path)
            continue

        doc_plan.instruction = instruction_for(doc_plan)
        doc_plan.rounds_needed = len(doc_plan.to_send)
        plan.documents.append(doc_plan)

    plan.untouched.sort()
    plan.already_current.sort()
    return plan


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def content_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Audit — is the declared link between a document and a fact actually real?
# ---------------------------------------------------------------------------

AUDIT_ANCHORED = "anchored"
AUDIT_WEAK = "weak"
AUDIT_PROSE = "prose"
AUDIT_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class AuditFinding:
    path: str
    key: str
    label: str
    status: str
    value: str
    count: int = 0
    note: str = ""


def audit(
    registry: Registry, table: FactTable, *, doc_text: dict[str, str] | None = None
) -> list[AuditFinding]:
    """Check every declared coverage claim against the document's actual text.

    Worth running before you need it. A document that declares it covers
    ``retry.max_attempts`` and does not contain the value anywhere is a
    coverage claim that will quietly do nothing on the day the constant
    changes — and the day the constant changes is the worst possible day to
    discover it. This turns that into something you can see on a Tuesday.
    """
    findings: list[AuditFinding] = []
    for spec in registry.documents():
        text = (
            doc_text.get(spec.path)
            if doc_text is not None
            else _read(registry.resolve(spec.path))
        )
        if text is None:
            findings.append(
                AuditFinding(spec.path, "", "", AUDIT_UNRESOLVED, "", note="cannot be read")
            )
            continue
        body = body_of(text)
        for key in spec.covers:
            value = table.values.get(key)
            if value is None or not value.ok:
                findings.append(
                    AuditFinding(
                        spec.path, key, value.label if value else key, AUDIT_UNRESOLVED, "",
                        note=(value.error.splitlines()[0] if value and value.error else "no such fact"),
                    )
                )
                continue
            if isinstance(value.text, list):
                missing = [item for item in value.text if occurrences(body, item) == 0]
                findings.append(
                    AuditFinding(
                        spec.path, key, value.label,
                        AUDIT_ANCHORED if not missing else AUDIT_PROSE,
                        value.display, count=len(value.text) - len(missing),
                        note="" if not missing else f"not found: {', '.join(missing)}",
                    )
                )
                continue
            hits = occurrences(body, str(value.text))
            if hits == 0:
                findings.append(
                    AuditFinding(
                        spec.path, key, value.label, AUDIT_PROSE, str(value.text),
                        note="the current value does not appear literally, so a change to "
                        "it can only be applied as a prose edit (--allow-prose) and cannot "
                        "be verified afterwards",
                    )
                )
            elif hits > 1 and _is_short(str(value.text)):
                findings.append(
                    AuditFinding(
                        spec.path, key, value.label, AUDIT_WEAK, str(value.text), count=hits,
                        note=f"appears {hits} times and is short enough to be ambiguous; "
                        f"add a `format:` to this fact so the anchor carries its own context",
                    )
                )
            else:
                findings.append(
                    AuditFinding(spec.path, key, value.label, AUDIT_ANCHORED,
                                 str(value.text), count=hits)
                )
    return findings


# ---------------------------------------------------------------------------
# The instruction
# ---------------------------------------------------------------------------


def instruction_for(doc: DocumentPlan) -> str:
    """The message sent to SuperDocs for one document.

    Written the way you would brief a careful colleague: the old and new
    strings quoted exactly, one numbered item per fact, and an explicit
    instruction not to tidy anything else up. Vague instructions invite wide
    edits, and a wide edit on an ADR is a rewrite of a decision record nobody
    approved.

    **Where two facts share the same old value the instruction stops quoting
    it.** This is carried over from Task 2's live run rather than reasoned
    about in the abstract: two fields that both read "None — single path" were
    given one substitution instruction naming that string twice with two
    different replacements. That is not a hard instruction, it is a
    contradiction, and the model resolved it differently in two documents that
    were supposed to agree. The same shape occurs here for free — a backoff of
    ``30`` seconds and a request timeout of ``30`` seconds are two facts with
    one spelling — so both that case and the short-and-repeated case anchor on
    the labelled sentence instead.
    """
    items: list[str] = []

    for change in doc.this_round:
        anchor = doc.anchors[change.key]
        n = len(items) + 1

        if change.is_list:
            items.append(_list_item(n, change))
            continue

        before, after = str(change.before_text), str(change.after_text)

        if anchor.kind == ANCHOR_UNANCHORED:
            items.append(
                f"{n}. This document describes the {_phrase(change.label)} in prose rather "
                f'than as the bare value "{after}". It is now "{after}" (it was "{before}"). '
                f"Update only the sentence or sentences that state it, including any "
                f"spelled-out form of the number, and leave the rest of the paragraph alone."
            )
        elif anchor.kind == ANCHOR_WEAK:
            # The caution comes from the anchor itself, which already knows
            # *why* the value is ambiguous — a sibling fact with the same
            # spelling, or the same text simply appearing twice. Recomputing it
            # here from the other items in the instruction is no longer
            # possible: an instruction now carries exactly one item.
            caution = anchor.note or (
                "this value appears elsewhere in the document; change only the one "
                "that states this fact."
            )
            items.append(
                f'{n}. In the sentence, row or field that states the {_phrase(change.label)} '
                f'— and only that one — set the value to "{after}". It currently reads '
                f'"{before}". Be careful: {caution} Leave every other occurrence of '
                f'"{before}" exactly as it is.'
            )
        else:
            # `literal` now means *exactly one* occurrence — anything repeated
            # is classified weak and takes the branch above. So the instruction
            # says so, and drops the old "there may be more than one
            # occurrence; change all of them". That sentence was licence to
            # edit text nobody had checked: on a live run a document contained
            # "3" once as a value and again inside "30 seconds", and a blanket
            # instruction is exactly how the second one gets rewritten.
            items.append(
                f'{n}. This document states the {_phrase(change.label)} as "{before}", '
                f'once. Replace that one occurrence with "{after}". Do not change any '
                f'other text that happens to contain "{before}".'
            )

    lines = [
        "Apply these specific corrections to this document. Make only these changes.",
        "",
        *items,
        "",
        "Do not reword anything else. Do not change any other number, name, heading or "
        "code sample. Do not add commentary, a note about the change, or a revision "
        "history entry. Do not touch the YAML front matter at the top of the file or any "
        "HTML comment. If a value I named does not appear in this document, skip that "
        "item and say so rather than changing something that looks similar.",
    ]
    return "\n".join(lines)


def _phrase(label: str) -> str:
    """A label as it reads mid-sentence.

    A blanket ``.lower()`` turns "API request timeout" into "api request
    timeout", which reads as a typo in an instruction whose whole authority
    comes from looking carefully written. Only the first word is lowered, and
    only when it is not an acronym.
    """
    if not label:
        return label
    first = label.split(" ", 1)[0]
    if len(first) > 1 and first.isupper():
        return label
    return label[0].lower() + label[1:]


def _list_item(n: int, change: FactChange) -> str:
    parts = [
        f"{n}. This document lists the {_phrase(change.label)}. The code now has a "
        f"different set."
    ]
    if change.added:
        parts.append("Add an entry for each of: " + ", ".join(f'"{a}"' for a in change.added) + ".")
    if change.removed:
        parts.append(
            "Remove the entry for each of: " + ", ".join(f'"{r}"' for r in change.removed) + "."
        )
    parts.append(
        "Match the formatting, column layout and wording style of the entries that are "
        "already there. Do not change any entry that I have not named."
    )
    return " ".join(parts)
