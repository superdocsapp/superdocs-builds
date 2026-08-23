"""MeetingSession — the Draft Engine (design doc's own term). Owns the
per-meeting state machine: consumes TranscriptEvents from whatever
TranscriptProvider it was given, batches them, classifies each batch,
turns it into a SuperDocs chat instruction, checks the result for
integrity, and publishes state changes to subscribers (the panel's SSE
stream).

Consumption is Protocol-only, deliberately: `_consume_events` only ever
calls `start`/`events` on `self._provider`, typed as `TranscriptProvider`.
It never imports or checks for `ManualTranscriptProvider` specifically —
that's what makes "RTMSProvider could replace ManualTranscriptProvider
without changing Draft Engine code" true by construction, not by
convention. Feeding the provider is a separate concern with a naturally
provider-specific entry point (an HTTP route for Manual; a websocket
handler for RTMS, in Milestone 4) — see `manual_provider` below.

State is flat, in-memory, and not persisted — the same M0 simplicity
decision this whole app was built under (PROGRESS.md, locked decision 3):
a backend restart loses in-progress session state, and that's an accepted,
stated limitation, not an oversight. See PROGRESS.md M3 for what that
means concretely here.
"""

from __future__ import annotations

import asyncio
import base64
import html as html_module
import re
import time

from app.core.config import get_settings
import logging

logger = logging.getLogger("session")

from app.drafting.batcher import Batcher
from app.drafting.classifier import (
    ADDITION,
    _draft_headings,
    SectionOperation,
    correction_values,
    build_section_operations,
    classify,
    resolve_intra_batch_correction,
)
from app.drafting.validator import (
    _anchor_present,
    _fact_anchors,
    content_landed_in_section,
    facts_preserved_in_html,
    foreign_fact_tokens,
    validate_correction,
    validate_proposal,
    validate_table_fill,
)
from app.drafting.templates import SOW, render_template, template_sections
from app.superdocs.client import SuperDocsClient
from app.superdocs.integrity import check_integrity, structural_defect
from app.superdocs.schemas import ExportResult
from app.transcript.factory import create_transcript_provider
from app.transcript.manual_provider import ManualTranscriptProvider
from app.transcript.provider import TranscriptEvent, TranscriptProvider
from app.transcript.rtms_provider import RTMSTranscriptProvider

# job_status values the panel renders as "SuperDocs operation status".
STATUS_IDLE = "idle"
STATUS_SENDING = "sending"
STATUS_POLLING = "polling"
STATUS_COMPLETED = "completed"
STATUS_BLOCKED = "blocked"
STATUS_ERROR = "error"


class _Document:
    """Per-document state — one session can hold multiple documents (SOW,
    Minutes, Proposal).  The active document's fields are delegated through
    MeetingSession properties for backward compatibility."""
    __slots__ = ("doc_id", "session_id", "template_key", "current_draft_html",
                 "draft_version", "approved_draft_version", "activity",
                 "last_export", "last_export_at", "_document_initialized",
                 "approved_by", "exported_by",
                 "custom_template_b64", "custom_template_name",
                 "fact_ledger", "reconcile_attempted", "unlanded_facts")

    def __init__(self, doc_id: str, session_id: str, template_key: str) -> None:
        self.doc_id = doc_id
        self.session_id = session_id
        self.template_key = template_key
        self.current_draft_html: str = ""
        # Every fact that has actually reached this document, as
        # (section, fact), for the document's whole life. The per-batch
        # preservation check only ever saw the CURRENT batch's facts, so
        # once a batch committed its content was never verified again: a
        # later batch could delete an earlier one's paragraph and every
        # individual check still passed. Confirmed live — Timeline &
        # Milestones logged "landed=True" and was absent from the finished
        # document.
        self.fact_ledger: list[tuple[str | None, str]] = []
        # Facts reconciliation has already tried to restore once. Without
        # this a fact the platform simply refuses to write would be retried
        # after every subsequent batch, forever.
        self.reconcile_attempted: set[str] = set()
        # Facts an operation was asked to write and that never arrived, as
        # (section, fact). fact_ledger records what DID reach the document,
        # so reconciliation could only ever recover content that landed and
        # later vanished — content that never landed at all was invisible to
        # it. Live, SuperDocs' Timeline edit deleted the Scope paragraph it
        # had just written, our preservation check correctly refused it, and
        # the revert that should have undone it returned 400. Scope was kept,
        # Timeline was dropped, and nothing was watching for it because it
        # had never been in the ledger to go missing from.
        self.unlanded_facts: list[tuple[str | None, str]] = []
        self.draft_version: int = 0
        self.approved_draft_version: int | None = None
        self.activity: list[dict] = []
        self.last_export: "ExportResult | None" = None
        self.last_export_at: float | None = None
        self._document_initialized = False
        # Who took the review action — the Zoom participant's display name
        # (screenName), self-reported by the client same as Task 1's audit
        # trail. Not authentication, just attribution: "Approved by X" reads
        # as a real review workflow instead of an anonymous checkmark.
        self.approved_by: str | None = None
        self.exported_by: str | None = None
        # The firm's own document, uploaded as a .docx. When present it is
        # what gets sent to SuperDocs as the starting document instead of
        # one of our built-in templates, so the deliverable comes back on
        # the letterhead and section structure the firm already uses — the
        # brief's "on the firm's template".
        self.custom_template_b64: str | None = None
        self.custom_template_name: str | None = None


_BLANK_STARTER_HTML = """<h1>Statement of Work</h1>
<h2>Project Details</h2>
<table><tr><td><strong>Client</strong></td><td></td></tr>
<tr><td><strong>Project</strong></td><td></td></tr>
<tr><td><strong>Date</strong></td><td></td></tr>
<tr><td><strong>Prepared by</strong></td><td></td></tr></table>
<h2>Executive Summary</h2><p></p>
<h2>Objectives</h2><p></p>
<h2>Scope of Work</h2><p></p>
<h2>Deliverables</h2><p></p>
<h2>Timeline &amp; Milestones</h2><p></p>
<h2>Budget / Commercial Terms</h2><p></p>
<h2>Assumptions &amp; Dependencies</h2><p></p>
<h2>Out of Scope</h2><p></p>
<h2>Next Steps</h2><p></p>"""
# Fallback for tests — active template is rendered via render_template().
_JOB_POLL_INTERVAL_SECONDS = 2.0
_JOB_POLL_DEADLINE_SECONDS = 300.0  # generous — the brief's own warning: edits can take minutes

# SuperDocs' own /v1/chat/async validation (confirmed live via its 422 body,
# see PROGRESS.md M3): session_id must match ^[a-zA-Z0-9_.-]+$. A real Zoom
# meeting UUID is base64-shaped and routinely contains /, +, = — this
# session_id is an opaque correlation key sent to SuperDocs, never decoded
# back, so substituting the disallowed characters is safe. self.meeting_uuid
# (below) keeps the real, un-sanitized value for our own routing/registry.
_SESSION_ID_UNSAFE = re.compile(r"[^a-zA-Z0-9_.\-]")

# Matches <h2>...</h2> followed by an empty <p></p> (no evidence).
# Removes the entire heading + empty paragraph block.
_EMPTY_SECTION = re.compile(
    # Attributes allowed on both tags. SuperDocs returns
    # <h2 data-chunk-id="...">Next Steps</h2><p data-chunk-id="..."></p>, so a
    # pattern demanding bare <h2> matched only our own starter HTML and never
    # a single document the platform had actually touched — the stripper was
    # inert for its entire real working life.
    r"<h2[^>]*>[^<]+</h2>\s*<p[^>]*>\s*</p>",
    re.IGNORECASE,
)


def _norm_text(html: str) -> str:
    """Document HTML as plain lowercase text, for presence checks."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).lower().strip()


# Below this, a fact is too thin for its absence to mean anything.
_RECONCILE_MIN_ANCHORS = 2


def _superseded_in_document(fact: str, section: str | None, html: str) -> bool:
    """Is this fact absent because something REPLACED it, rather than lost?

    Recovery's worst failure is resurrecting a value the speaker corrected
    away. The ledger retires a superseded fact when the correcting batch
    commits — but a correction batch that FAILS never reaches that code, so
    the old figure stays on the ledger, reads as missing, and gets restored.
    Live: "RECONCILE restored 'Our total budget is $45,000.'" moments after
    the speaker had changed it to $55,000, leaving the document holding both.

    So: if the fact's own section already carries a DIFFERENT value of the
    same kind, the fact was superseded. Leave it alone.
    """
    from app.drafting.classifier import (
        _DATE_VALUE_RE,
        _MONEY_VALUE_RE,
        _section_body,
    )
    body = _section_body(html, section) if section else (html or "")
    body = _norm_text(body)
    for pattern in (_MONEY_VALUE_RE, _DATE_VALUE_RE):
        mine = {m.group(0).strip().lower() for m in pattern.finditer(fact)}
        if not mine:
            continue
        theirs = {m.group(0).strip().lower() for m in pattern.finditer(body)}
        if theirs and not (mine & theirs):
            return True
    return False


def _fact_still_present(fact: str, document_text: str) -> bool:
    """Is this fact still in the document?

    Uses the gate's own anchors and its own morphological tolerance, so
    reconciliation and validation can never disagree about what "present"
    means — a second, looser notion of presence here would re-drive facts
    that are in fact there and duplicate them.
    """
    anchors = _fact_anchors(fact)
    # One weak anchor is not evidence of anything. A thin utterance ("Um,
    # so.") yields a single ordinary word, and treating its absence as a
    # deletion would have reconciliation re-drive conversational noise into
    # the document — recovery has to be much surer of itself than the gate,
    # because it ADDS content on its own initiative rather than refusing it.
    # Quality, not count. A date or money anchor is the strongest evidence
    # there is — "september 15th" is a single anchor and its disappearance
    # is unambiguous. A count-based rule threw exactly those away while
    # keeping thin word-only facts, which is backwards.
    decisive = any(any(ch.isdigit() for ch in a) for a in anchors)
    if not decisive and len(anchors) < _RECONCILE_MIN_ANCHORS:
        return True
    return all(_anchor_present(a, document_text) for a in anchors)


def _section_missing(section: str | None, html: str) -> bool:
    """Has this section's HEADING disappeared from the document?

    Different, and much stronger, evidence than "I cannot find this
    sentence". Reconciliation is normally restricted to date/money-anchored
    facts because prose gets paraphrased and a near-miss anchor would have
    recovery duplicate a paragraph that is already there. When the whole
    heading is gone there is nothing to duplicate — the section is not
    reworded, it is absent — so prose facts belonging to it are safe to
    re-drive.

    Live: a revert issued to undo ONE operation removed the section a
    PREVIOUS operation had committed. "Scope of Work" and "Budget /
    Commercial Terms" both logged landed=True and the finished remote
    document had only 7 of its 9 headings.
    """
    if not section:
        return False
    from app.drafting.classifier import _HEADING_RE
    present = {
        re.sub(r"<[^>]+>", "", h).replace("&amp;", "&").strip().lower()
        for h in _HEADING_RE.findall(html or "")
    }
    return section.strip().lower() not in present


def _drop_sections(html: str, names: set[str]) -> str:
    """Remove the named sections (heading and body) from local HTML.

    Used only to make the local draft stop claiming content the remote no
    longer has. A local copy that disagrees with the remote is worse than
    one that is missing something: reconciliation compares against it, so a
    stale local draft silently suppresses the very recovery that would fix
    the document.
    """
    if not names:
        return html
    wanted = {n.strip().lower() for n in names}
    # Split on headings and keep each heading with the body that follows it,
    # so a section is dropped whole. A single regex that tried to match
    # "heading plus everything until the next heading" swallowed the NEXT
    # section's body as well.
    parts = re.split(r"(<h[1-6][^>]*>.*?</h[1-6]>)", html or "", flags=re.S | re.I)
    out, skipping = [], False
    for part in parts:
        if re.match(r"<h[1-6]", part or "", re.I):
            text = re.sub(r"<[^>]+>", "", part).replace("&amp;", "&").strip().lower()
            skipping = text in wanted
            if skipping:
                continue
        elif skipping:
            continue
        out.append(part)
    return "".join(out)


def _strip_empty_sections(html: str) -> str:
    """Remove any section whose body is only an empty paragraph.
    This ensures unsupported sections never appear in the document."""
    return _EMPTY_SECTION.sub("", html)


_H2_RE = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
_H2_SPLIT_RE = re.compile(r"<h2[^>]*>.*?</h2>", re.IGNORECASE | re.DOTALL)


def _empty_heading_texts(html: str) -> list[str]:
    """Headings whose body (everything up to the next heading) has zero
    visible text — the same emptiness test the panel already applies
    client-side (App.jsx's parseSections/bodyText, styled `.empty`), so
    'is this section empty' means the same thing here as it does on
    screen. Used to bring the exported document in line with what the
    panel already shows before export — see export_draft()."""
    headings = [html_module.unescape(re.sub(r"<[^>]+>", "", h)).strip() for h in _H2_RE.findall(html or "")]
    bodies = _H2_SPLIT_RE.split(html or "")[1:]
    empty = []
    for heading, body in zip(headings, bodies):
        if heading and not re.sub(r"<[^>]+>", "", body).strip():
            empty.append(heading)
    return empty


def _is_structural_failure(reason: str) -> bool:
    """A rejection caused by the model emitting template-filler structure
    (headings, placeholders, new tables) rather than converging on content,
    or inventing content the source never said. These warrant one
    explicit-constraint retry, not a full retry budget."""
    reason_l = (reason or "").lower()
    return (
        "heading" in reason_l
        or "placeholder" in reason_l
        or "please fill" in reason_l
        or "new table" in reason_l
        or "unsupported content" in reason_l
    )


def _is_conflict(exc: Exception) -> bool:
    """True when the exception is an HTTP 409 Conflict from SuperDocs.

    A 409 means the remote session is in a state that rejects the call —
    retrying the same call is guaranteed to fail again. Detected via duck
    typing on httpx's response attribute so this module never imports httpx.
    """
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None) == 409


class MeetingSession:
    def __init__(
        self,
        meeting_uuid: str,
        client: SuperDocsClient,
        provider: TranscriptProvider,
        manual_provider: ManualTranscriptProvider | RTMSTranscriptProvider | None = None,
        *,
        # Batcher thresholds, overridable so tests don't wait on real
        # timers — same reasoning as Batcher's own defaults. Milestone 6
        # live-feel tuning (Phase 4): 2s silence flush / 8s hard ceiling so
        # the panel keeps pace with the conversation; the old 3.5s/20s
        # values made the document feel stale during continuous speech.
        # Both thresholds MUST exceed the audio-fetcher's 6s chunk interval.
        # Audio no longer arrives when someone stops speaking — it arrives on
        # a fixed 6s clock, so any gap below 6s elapses after every single
        # chunk and fires unconditionally. At the old 2s/3s a batch was
        # always exactly one chunk, cut wherever the clock landed: half a
        # clause per SuperDocs call, unwritable as prose, denied through the
        # whole retry budget, and routed on a fragment with no topic. 7s lets
        # continuous speech accumulate; 15s bounds it.
        silence_gap_seconds: float = 7.0,
        size_ceiling_chars: int = 400,
        # The 3s that replaced the old 8s ceiling fixed mega-batch fact loss
        # (P0 forensic audit, val8) but predates fixed-interval chunking. The
        # size ceiling above — not the clock — is what now caps batch size;
        # 15s only bounds how long content can wait.
        max_wait_seconds: float = 15.0,
        poll_interval_seconds: float = _JOB_POLL_INTERVAL_SECONDS,
    ) -> None:
        self.meeting_uuid = meeting_uuid
        safe_uuid = _SESSION_ID_UNSAFE.sub("_", meeting_uuid)
        self.session_id = f"zoom-{safe_uuid}-{int(time.time())}"
        self._client = client
        self._provider = provider
        # Set whenever the active provider supports manual override input
        # (Manual always; RTMSTranscriptProvider too, Milestone 4, as its
        # own fallback-without-restarting mechanism) — the one thing on
        # this class that's provider-specific, and only because "accept
        # typed input" has no origin-agnostic form to abstract.
        self.manual_provider = manual_provider

        # Multi-document: one session holds ≥1 documents.  Properties below
        # delegate to the active document for backward compatibility.
        self._documents: dict[str, _Document] = {}
        doc_id = f"doc-{int(time.time())}"
        doc = _Document(doc_id, self.session_id, SOW)
        self._documents[doc_id] = doc
        self._active_doc: _Document = doc

        self.transcript_history: list[TranscriptEvent] = []
        # activity / current_draft_html / draft_version / approved_draft_version
        # / last_export / last_export_at are now PROPERTIES delegating to
        # _active_doc (see property block below).
        self.job_status: str = STATUS_IDLE
        self.error: str | None = None
        # Control-channel state for the Mac capture-helper (Architecture B).
        # Values: disconnected | connecting | listening | stopping | ready.
        # NOT audio truth — it only reflects the helper ACKing the START/STOP
        # command, never whether sound is actually being captured.
        self.helper_status: str = "disconnected"
        # Which heading SuperDocs is actively editing right now, or None
        # between operations — lets the panel show "drafting…" against the
        # real target section instead of the whole template skeleton.
        self.active_section: str | None = None
        # Retry / recovery state — stored per-batch so the panel can offer
        # retry/accept/discard actions on failure or integrity block.
        self._failed_batch: list[TranscriptEvent] | None = None
        # Batches that arrived while _unrecoverable was set — held here
        # instead of dropped, so a retry replays everything spoken during
        # the wedge, not just the one batch that triggered it.
        self._pending_batches: list[list[TranscriptEvent]] = []
        self._pending_blocked: dict | None = None
        # Generation counter: incremented on reset().
        self._generation: int = 0
        # Active template metadata.
        self._template_meta: dict[str, str] = {}

        self._document_initialized = False
        self._inflight_lock = asyncio.Lock()
        self._subscribers: list[asyncio.Queue] = []
        self._consumer_task: asyncio.Task | None = None
        self._poll_interval_seconds = poll_interval_seconds
        # SuperDocs model configuration read once at session creation. None
        # → server defaults (core + balanced); set via env vars
        # SUPERDOCS_MODEL_TIER / SUPERDOCS_THINKING_DEPTH for the M1-M6
        # experiment.
        settings = get_settings()
        self._model_tier = settings.superdocs_model_tier
        self._thinking_depth = settings.superdocs_thinking_depth
        # HITL gate bookkeeping: how many chat turns this session has issued
        # (each = one user message — the revert turn_index reference) and the
        # durable document id used by the free structure read.
        self._turn_count = 0
        self._durable_document_id: str | None = None
        self._failed_batch_holder: str | None = None
        # Set when a batch fails in a way retries cannot fix (a SuperDocs
        # conflict, or an approval that settled externally but never settled
        # locally). While set, subsequent batches are NOT processed — the
        # session is in a terminal error and only explicit recovery (retry/
        # clear) may resume it. Prevents the 409 death-spiral.
        self._unrecoverable: bool = False
        self.batcher = Batcher(
            self._handle_batch,
            silence_gap_seconds=silence_gap_seconds,
            size_ceiling_chars=size_ceiling_chars,
            max_wait_seconds=max_wait_seconds,
        )

    # ---- per-document property delegation (Phase 3: Multi-document) -----------
    # All draft-related state delegates to _active_doc.  Backward-compatible:
    # existing code reads/writes these names directly; the properties route
    # them to the active document's _Document instance.

    @property
    def current_draft_html(self) -> str:
        return self._active_doc.current_draft_html

    @current_draft_html.setter
    def current_draft_html(self, value: str) -> None:
        self._active_doc.current_draft_html = value

    @property
    def draft_version(self) -> int:
        return self._active_doc.draft_version

    @draft_version.setter
    def draft_version(self, value: int) -> None:
        self._active_doc.draft_version = value

    @property
    def approved_draft_version(self) -> int | None:
        return self._active_doc.approved_draft_version

    @approved_draft_version.setter
    def approved_draft_version(self, value: int | None) -> None:
        self._active_doc.approved_draft_version = value

    @property
    def activity(self) -> list[dict]:
        return self._active_doc.activity

    @property
    def last_export(self) -> "ExportResult | None":
        return self._active_doc.last_export

    @last_export.setter
    def last_export(self, value: "ExportResult | None") -> None:
        self._active_doc.last_export = value

    @property
    def last_export_at(self) -> float | None:
        return self._active_doc.last_export_at

    @property
    def approved_by(self) -> str | None:
        return self._active_doc.approved_by

    @approved_by.setter
    def approved_by(self, value: str | None) -> None:
        self._active_doc.approved_by = value

    @property
    def exported_by(self) -> str | None:
        return self._active_doc.exported_by

    @exported_by.setter
    def exported_by(self, value: str | None) -> None:
        self._active_doc.exported_by = value

    @last_export_at.setter
    def last_export_at(self, value: float | None) -> None:
        self._active_doc.last_export_at = value

    @property
    def _document_initialized(self) -> bool:
        return self._active_doc._document_initialized

    @_document_initialized.setter
    def _document_initialized(self, value: bool) -> None:
        self._active_doc._document_initialized = value

    @property
    def active_template_key(self) -> str:
        return self._active_doc.template_key

    @active_template_key.setter
    def active_template_key(self, value: str) -> None:
        self._active_doc.template_key = value

    # ---- document management (Phase 3) ----------------------------------------

    async def create_document(self, *, template_key: str = SOW) -> dict:
        """Create a new document and make it active.  Returns a snapshot
        so the frontend can update its document list."""
        import time as _time
        doc_id = f"doc-{int(_time.time() * 1000)}"
        doc = _Document(
            doc_id,
            f"{self.session_id}-{len(self._documents) + 1}",
            template_key,
        )
        self._documents[doc_id] = doc
        self._active_doc = doc
        return {"document_id": doc_id, "template_key": template_key}

    async def activate_document(self, document_id: str) -> dict:
        """Switch to a different document.  Raises ValueError if unknown."""
        if document_id not in self._documents:
            raise ValueError(f"unknown document: {document_id}")
        self._active_doc = self._documents[document_id]
        return {"document_id": document_id, "template_key": self._active_doc.template_key}

    async def delete_document(self, document_id: str) -> None:
        """Delete a document.  Raises ValueError if it doesn't exist or is
        the last remaining document."""
        if document_id not in self._documents:
            raise ValueError(f"unknown document: {document_id}")
        if len(self._documents) <= 1:
            raise ValueError("cannot delete the last document")
        del self._documents[document_id]
        # If the deleted doc was active, switch to any remaining doc
        if self._active_doc.doc_id == document_id:
            self._active_doc = next(iter(self._documents.values()))

    def _active_doc_snapshot(self) -> dict:
        """Return metadata-only snapshot of the active document."""
        doc = self._active_doc
        return {
            "document_id": doc.doc_id,
            "template_key": doc.template_key,
            "draft_version": doc.draft_version,
            "approved_draft_version": doc.approved_draft_version,
        }

    def _document_list(self) -> list[dict]:
        """Return [{document_id, template_key, draft_version}, ...] for all docs."""
        return [
            {
                "document_id": d.doc_id,
                "template_key": d.template_key,
                "draft_version": d.draft_version,
            }
            for d in self._documents.values()
        ]

    async def start(self) -> None:
        await self._provider.start({"meeting_uuid": self.meeting_uuid})
        self._consumer_task = asyncio.create_task(self._consume_events())

    # ---- Milestone 6: explicit live-listening lifecycle ---------------------
    #
    # start() above must NOT begin live transcription — the panel's
    # "Start listening" is an explicit user action, so the actual bot
    # lifecycle lives here, behind methods the listen routes call. Both
    # raise ValueError when the active provider has no live-listening
    # capability (Manual: nothing to connect; RTMS: listening starts when
    # Zoom's rtms_started webhook arrives, not from a panel button) —
    # the routes turn that into a 409, same convention as submit/approve.

    @property
    def helper_connected(self) -> bool:
        """Whether any capture-helper is connected to the backend right now.
        Read at snapshot time from the shared registry so /state reflects
        live helper availability without a request-scoped reference."""
        from app.helper.registry import helper_registry

        return helper_registry.connected

    async def set_helper_status(self, status: str) -> None:
        """Update the helper control-channel state and publish it. This is
        command/ACK truth only — it never claims audio is being captured."""
        self.helper_status = status
        await self._publish({"type": "helper_status", "status": status})

    async def start_listening(
        self,
        *,
        meeting_number: str | None = None,
        meeting_url: str | None = None,
        passcode: str | None = None,
    ) -> str:
        if not hasattr(self._provider, "begin_listening"):
            raise ValueError("the active transcript provider does not support live listening")
        await self._provider.begin_listening(
            meeting_number=meeting_number, meeting_url=meeting_url, passcode=passcode
        )
        return self._provider.status()

    async def stop_listening(self) -> str:
        # Protocol-conformant for every provider; for Vexa this also stops
        # the bot (DELETE /bots/zoom/<id>) so no orphaned bot keeps
        # listening after the user stops it.
        await self._provider.stop()
        return self._provider.status()

    # ---- error recovery (Phase 1: retry / blocking-card resolution) ------------

    async def retry_last_batch(self) -> None:
        """Re-run the most recently failed batch.  Raises ValueError if no
        failed batch is available (the error state has already been cleared
        by a subsequent successful batch)."""
        if self._failed_batch is None:
            raise ValueError("nothing to retry")
        batch = self._failed_batch
        self._failed_batch = None
        # Explicit user-initiated recovery — the terminal-error gate that
        # blocked further automatic processing is lifted for this attempt.
        self._unrecoverable = False
        await self._handle_batch(batch)
        # Drain content that arrived (and was held, not dropped) while the
        # session was wedged. Stop as soon as a replay re-wedges — whatever
        # is left stays queued for the next retry rather than being lost.
        while not self._unrecoverable and self._pending_batches:
            await self._handle_batch(self._pending_batches.pop(0))

    async def resolve_blocking_card(self, *, action: str) -> None:
        """Accept or discard an integrity-blocked batch.  'accept' commits
        the flagged html_after (human override of integrity gate).  'discard'
        clears the block without changing the draft."""
        if self._pending_blocked is None:
            raise ValueError("no blocking card to resolve")
        blocked = self._pending_blocked
        self._pending_blocked = None
        if action == "accept":
            self.current_draft_html = blocked["html_after"]
            self.draft_version += 1
            self.error = None
            await self._set_status(STATUS_COMPLETED)
            entry = {
                "classification": blocked["classification"],
                "summary": blocked["text"][:120],
                "timestamp": time.time(),
            }
            self.activity.append(entry)
            await self._publish({"type": "activity", "entry": entry})
            await self._publish(
                {"type": "draft_updated", "html": blocked["html_after"],
                 "draft_version": self.draft_version}
            )
        elif action == "discard":
            self.error = None
            await self._set_status(STATUS_COMPLETED)
        else:
            raise ValueError(f"unknown blocking card action: {action}")

    # ---- clear / reset (Phase 1) ----------------------------------------------

    async def reset(self) -> None:
        """Clear all meeting data: transcript, activity, draft, review/export
        state.  Does NOT stop the provider or disconnect listening.  Does NOT
        clear credentials.  Preserves the active template key."""
        self._generation += 1
        self._clearing = True
        try:
            async with self._inflight_lock:
                await self.batcher.clear()
                self.transcript_history = []
                # Preserve the active template key across reset
                prev_key = self._active_doc.template_key
                import time as _time
                doc_id = f"doc-{int(_time.time())}"
                self._active_doc = _Document(doc_id, self.session_id, prev_key)
                self._documents = {doc_id: self._active_doc}
                self.job_status = STATUS_IDLE
                self.error = None
                self._failed_batch = None
                self._pending_batches = []
                self._pending_blocked = None
                self._unrecoverable = False
                # Clear Vexa provider dedup set so repeated speech isn't blocked
                if hasattr(self._provider, 'clear_seen'):
                    self._provider.clear_seen()
                await self._publish({
                    "type": "session_reset",
                    "active_document_id": self._active_doc.doc_id,
                    "active_template_key": self._active_doc.template_key,
                    "documents": self._document_list(),
                })
        finally:
            self._clearing = False

    async def set_active_template(
        self, *, key: str, topic: str = "", client: str = "", prepared_by: str = ""
    ) -> str:
        """Switch to a different template.  Re-initializes the document if
        one hasn't been created yet.  If a draft already exists, the
        template only takes effect on the next reset.  Returns the rendered
        starter HTML."""
        self.active_template_key = key
        self._template_meta = {
            "topic": topic or "",
            "client": client or "",
            "prepared_by": prepared_by or "",
        }
        html = render_template(
            key,
            topic=self._template_meta.get("topic", ""),
            client=self._template_meta.get("client", ""),
            prepared_by=self._template_meta.get("prepared_by", ""),
        )
        return html

    async def set_custom_template(self, *, file_base64: str, filename: str) -> str:
        """Adopt the firm's own document as the starting point.

        Uploaded straight to SuperDocs rather than converted locally: it
        returns the HTML it will actually edit, so what the panel routes
        against is the real structure of the firm's file — its headings, its
        table, its wording — not our approximation of it. Sections are
        therefore whatever the document already contains; the routing rules
        that match on heading names still apply where the names line up, and
        anything unrecognised falls to the "most appropriate section" path.
        """
        if not file_base64:
            raise ValueError("no file provided")
        doc = self._active_doc
        upload = await self._client.upload_base64(
            file_base64=file_base64,
            filename=filename or "template.docx",
            session_id=doc.session_id,
            return_html=True,
        )
        html = upload.html
        if not (html or "").strip():
            raise ValueError("the uploaded file produced no readable content")
        doc.custom_template_b64 = file_base64
        doc.custom_template_name = filename
        doc.current_draft_html = html
        doc._document_initialized = True
        self._durable_document_id = None
        if hasattr(self._client, "get_session_documents"):
            try:
                for d in await self._client.get_session_documents(session_id=doc.session_id):
                    if d.get("durable_document_id"):
                        self._durable_document_id = d["durable_document_id"]
                        break
            except Exception as exc:
                logger.warning("could not resolve durable document id: %s", exc)
        await self._publish({
            "type": "draft_updated",
            "html": doc.current_draft_html,
            "draft_version": doc.draft_version,
        })
        await self._publish({"type": "custom_template", "filename": filename})
        return html

    async def _consume_events(self) -> None:
        async for event in self._provider.events():
            if getattr(self, '_clearing', False):
                continue
            self.transcript_history.append(event)
            await self._publish(
                {
                    "type": "transcript_received",
                    "event": event.model_dump(),
                }
            )
            logger.info("TRANSCRIPT_RECEIVED: uuid=%r seq=%d subs=%d text=%r",
                self.meeting_uuid, event.sequence, len(self._subscribers), event.text[:60])
            await self.batcher.add(event)

    # ---- the per-batch pipeline (design doc §15) ---------------------------

    async def _handle_batch(self, batch: list[TranscriptEvent]) -> None:
        text = " ".join(event.text for event in batch)
        # A repair usually follows its mistake in the same breath, so both
        # land in one batch — "Our total budget is $45,000. Actually, no,
        # make it $55,000." Left alone, the draft does not yet hold the old
        # figure when classification runs, so the repair reads as new
        # information and SuperDocs receives two competing values; the live
        # run left Budget empty rather than pick one. Resolve it first, so
        # the batch only ever carries the value that survived.
        # What the people in the room actually said, kept verbatim for the
        # activity log. resolve_intra_batch_correction rewrites the text for
        # the INSTRUCTION — dropping superseded values and bare cue markers
        # — which is right for SuperDocs and wrong for provenance: the log
        # started reporting "November 15th." for someone who said
        # "Correction. November 15th.", quietly editing the record of the
        # meeting.
        spoken_text = text
        text = resolve_intra_batch_correction(text)
        captured_text = text
        # Pin the active document — tab switch mid-flight must NOT
        # contaminate a different document.
        doc = self._active_doc
        gen = self._generation

        async with self._inflight_lock:
            if gen != self._generation:
                return
            # If the active doc changed while we were queued, drop this
            # batch — we pinned the wrong document.
            if self._active_doc.doc_id != doc.doc_id:
                return
            # Terminal-error gate: after an unrecoverable failure (SuperDocs
            # conflict, or an approval that settled externally but never
            # locally), do not keep processing later batches — the remote
            # session is in an unknown state and every further call risks the
            # same 409 spiral. Only explicit recovery (retry / clear) clears
            # the flag.
            if self._unrecoverable:
                self._pending_batches.append(batch)
                await self._publish(
                    {"type": "error", "message": self.error, "pending_batches": len(self._pending_batches)}
                )
                return
            # Classify against the pinned document's draft at lock time.
            if any(getattr(e, 'is_correction', False) for e in batch):
                from app.drafting.classifier import CORRECTION
                classification = CORRECTION
            else:
                # Classify what was SAID, not what we rewrote for the
                # instruction. resolve_intra_batch_correction strips the bare
                # cue ("Correction.") that flags a repair, so classifying the
                # rewritten text lost the very signal that identifies it: a
                # cross-batch correction read as an addition, the old value
                # was never retired, and recovery then restored the figure
                # the speaker had just replaced.
                classification = classify(spoken_text, doc.current_draft_html)
            # Initialize the document once, before any instruction is built —
            # section routing parses headings from the live draft, and on the
            # first batch that draft is the initialized template, never the
            # empty starter. Same bounded retry as the operations below.
            retries = 3
            if not doc._document_initialized:
                init_exc: Exception | None = None
                for attempt in range(retries):
                    try:
                        await self._initialize_document()
                        doc._document_initialized = True
                        break
                    except Exception as exc:
                        init_exc = exc
                        if attempt < retries - 1:
                            await asyncio.sleep(2 ** attempt)
                        continue
                else:
                    self._failed_batch = batch
                    self.error = str(init_exc)
                    await self._publish({"type": "error", "message": str(init_exc)})
                    await self._set_status(STATUS_ERROR)
                    return

            # Section-by-section orchestration with the HITL validation gate.
            # The batch is split into one bounded instruction per target
            # section (in live-draft heading order). Each operation runs
            # with approval_mode="ask_every_time": SuperDocs proposes the
            # edit, OUR validator decides whether it is acceptable, and only
            # a validated proposal is approved. The model matrix proved
            # placement is nondeterministic at every tier — the gate is the
            # reliability mechanism, not model escalation.
            ops = build_section_operations(
                classification, captured_text, doc.current_draft_html, doc.template_key
            )
            if not ops:
                # Filler-only batch ("Hi.") — nothing to edit, nothing to
                # commit: no SuperDocs call, no version bump, no activity.
                return
            self._failed_batch_holder = None

            # One line per batch naming exactly what was built from it. Without
            # this, a section that simply never gets an operation is
            # indistinguishable in the logs from one whose operation failed —
            # and a live run lost Timeline, Budget and Deliverables with no
            # rejection recorded anywhere, which took far too long to even
            # localise.
            logger.info(
                "BATCH ROUTED: text=%r -> ops=%s",
                captured_text[:110],
                [(o.table_field or o.section or "unrouted") for o in ops],
            )

            # Distinctive tokens of the whole batch — each operation's
            # proposal must carry only its own facts, never another
            # operation's (cross-section contamination check). Common words
            # legitimately recur across sections and are excluded.
            all_facts = [f for o in ops for f in o.facts]

            # The draft as it stood BEFORE this batch — the correction's
            # old value has to be looked up against the document that still
            # contains it.
            pre_batch_html = doc.current_draft_html

            # Batch-level bounded retry: a batch can fail because the
            # platform's sequential edits dropped earlier content (caught by
            # the preservation check) or transiently. Roll back and re-run
            # the whole batch at most twice before surfacing the error.
            batch_result = await self._run_batch_ops(
                ops, all_facts, classification, captured_text, doc, batch
            )
            if batch_result is None:
                return  # rolled back + error/blocked surfaced by the runner
            current_html = batch_result

            # A corrected value is SUPPOSED to be gone. Retire the superseded
            # fact from the ledger before recording this batch, or recovery
            # reads the correction as content loss and restores the very
            # figure the speaker just replaced — reconciliation would fight
            # every correction, putting $45,000 back after "make it $55,000".
            if any(op.is_correction for op in ops):
                retired, _new = correction_values(spoken_text, pre_batch_html)
                if retired:
                    needle = retired.lower()
                    doc.fact_ledger = [
                        (sec, f) for sec, f in doc.fact_ledger
                        if needle not in f.lower()
                    ]

            # Record only what is VERIFIABLY in the resulting document, not
            # everything this batch asked for. A fact the platform paraphrased
            # past our anchors was never observable to begin with, and putting
            # it in the ledger would have recovery chase it forever — the
            # ledger has to mean "this was really here", or "it is gone now"
            # proves nothing.
            committed_text = _norm_text(current_html)
            for op in ops:
                for fact in op.facts:
                    if _fact_still_present(fact, committed_text):
                        doc.fact_ledger.append((op.section, fact))

            # Clear transient error on a successful batch — but keep a
            # partial-failure notice, which is not transient: a section that
            # could not be added is something the reviewer must see.
            self.error = getattr(self, "_batch_partial_error", None)
            doc.draft_version += 1
            self._failed_batch = None
            self._pending_blocked = None
            await self._set_status(STATUS_COMPLETED)
            entry = {
                "classification": classification,
                "summary": spoken_text[:120],
                "timestamp": time.time(),
            }
            doc.activity.append(entry)
            await self._publish({"type": "activity", "entry": entry})
            # Last thing in the batch, and only when nothing else is queued:
            # check everything ever written, not just what this batch wrote.
            await self._reconcile_missing_facts(doc)

            # doc.current_draft_html, NOT the local `current_html` captured
            # before reconciliation ran. Reconciliation can commit an edit
            # and publish it, and this publish lands after it — sending the
            # pre-reconciliation HTML here stamped the restored content's
            # own version number onto the draft that was missing it, so the
            # panel showed a recovered section for an instant and then lost
            # it again, with no version change to reveal the overwrite.
            await self._publish(
                {
                    "type": "draft_updated",
                    "html": doc.current_draft_html,
                    "draft_version": doc.draft_version,
                }
            )


    # How many vanished facts one reconciliation pass will try to restore.
    # A bound, not a target: if many facts are missing something larger is
    # wrong and quietly issuing a dozen extra edits would make it worse.
    _RECONCILE_MAX = 3

    async def _reconcile_missing_facts(self, doc) -> None:
        """Restore content that reached the document and later vanished.

        The gate stops bad content going IN. Nothing watched content going
        OUT: a later batch's edit could drop an earlier batch's paragraph
        and every per-batch check still passed, because each only ever knew
        its own facts. Live, Timeline & Milestones logged "landed=True" and
        was missing from the finished document, and the same shape accounts
        for most of the run-to-run variance — a section is not mis-drafted,
        it is written and then silently deleted.

        Deliberately the weakest possible action:
          - runs only when the pipeline is otherwise healthy and idle
          - re-drives at most _RECONCILE_MAX facts, once each, ever
          - goes through the SAME gate as any other edit, so it can never
            put unvalidated content into the document
          - swallows every failure — a document that is missing a paragraph
            must never become a document that is broken
        """
        if self._unrecoverable or self._pending_batches:
            return
        if not doc.fact_ledger and not doc.unlanded_facts:
            return
        text = _norm_text(doc.current_draft_html)
        # Two sources, one meaning: content that should be in this document
        # and is not. fact_ledger holds what landed and may since have been
        # deleted; unlanded_facts holds what an operation was asked to write
        # and never delivered. Both are re-driven through exactly the same
        # bounded, gated path below — a failed section gets one more chance,
        # never a special one.
        # `verified` marks facts that were once observed IN the document
        # (fact_ledger) as opposed to ones an operation was asked to write
        # and never delivered (unlanded_facts). Only the first kind can have
        # "its section has vanished" mean anything: a section that was never
        # written has no heading either, and that is the ordinary state of
        # every section nobody has spoken to yet.
        missing = [
            (section, fact, verified)
            for source, verified in ((doc.fact_ledger, True), (doc.unlanded_facts, False))
            for section, fact in source
            if fact not in doc.reconcile_attempted
            and not _fact_still_present(fact, text)
        ]
        if not missing:
            return
        # Act ONLY on decisive evidence: a fact anchored by a date or an
        # amount. Prose is paraphrased freely by the platform, and an anchor
        # our tolerance happens to miss would have recovery "restore" text
        # that is already there — turning a cosmetic miss into a duplicated
        # paragraph, which is worse than the gap it was fixing. A vanished
        # "September 15th" or "$45,000" is unambiguous, and those are the
        # losses actually seen live (Timeline & Milestones, Budget).
        # Everything else is logged for diagnosis and left alone.
        decisive = [
            (section, fact) for section, fact, verified in missing
            if (
                any(any(c.isdigit() for c in a) for a in _fact_anchors(fact))
                # ...or this content was confirmed present and the whole
                # section it lived in has since disappeared. That is not a
                # paraphrase our tolerance missed — there is no section left
                # to have paraphrased it, and nothing restoring it could
                # duplicate. Still requires enough anchors to have been
                # genuinely verifiable, so thin utterances stay out.
                or (
                    verified
                    and _section_missing(section, doc.current_draft_html)
                    and len(_fact_anchors(fact)) >= _RECONCILE_MIN_ANCHORS
                )
            )
            and not _superseded_in_document(fact, section, doc.current_draft_html)
        ]
        logger.warning(
            "RECONCILE %d fact(s) missing, %d decisive: %s",
            len(missing), len(decisive), [f[:48] for _, f, _v in missing[:3]]
        )
        if not decisive:
            return
        # Recovery must leave the session exactly as it found it — running an
        # edit here moved job_status to "polling" AFTER the batch had already
        # reported "completed", so a finished session looked permanently busy.
        status_before = self.job_status
        for section, fact in decisive[:self._RECONCILE_MAX]:
            doc.reconcile_attempted.add(fact)
            # Built through the ordinary path, never hand-rolled: the
            # instruction then carries exactly the same targeting and
            # structural constraints as any other edit, and there is no
            # second way of describing an edit that could drift from it.
            rebuilt = build_section_operations(
                ADDITION, fact, doc.current_draft_html, doc.template_key
            )
            if not rebuilt:
                continue
            op = rebuilt[0]
            try:
                updated, _blocked = await self._run_gated_operation(
                    op, doc.current_draft_html, doc, ADDITION, fact,
                )
            except Exception as exc:  # never let recovery break the session
                logger.warning("RECONCILE failed for %r: %s", fact[:48], exc)
                continue
            if updated:
                doc.current_draft_html = updated
                doc.draft_version += 1
                await self._publish({
                    "type": "draft_updated",
                    "html": updated,
                    "draft_version": doc.draft_version,
                })
                logger.info("RECONCILE restored %r to %s", fact[:48], section)
        await self._set_status(status_before)

    async def _redrive_dropped(self, doc, dropped, classification: str) -> str | None:
        """Re-add content another operation deleted, when no revert can.

        Only ever called with facts `facts_preserved_in_html` has just shown
        to be absent from the HTML SuperDocs returned — that proof is the
        whole licence for this. Re-driving content the document still holds
        is how a live document ended up with two Project Details tables, so
        the absence must be established, never assumed.

        One attempt per section, through the ordinary gate, so restored
        content is validated exactly like any other edit. Returns the new
        HTML, or None if nothing could be restored. Never raises: failing to
        recover a paragraph must not also break the batch.
        """
        by_section: dict[str, list[str]] = {}
        for section, fact in dropped:
            by_section.setdefault(section, []).append(fact)
        html = doc.current_draft_html
        restored_any = False
        for section, facts in list(by_section.items())[:self._RECONCILE_MAX]:
            text = " ".join(facts)
            rebuilt = build_section_operations(
                ADDITION, text, html, doc.template_key
            )
            op = next((o for o in rebuilt if o.section == section), None)
            if op is None:
                continue
            try:
                updated, _blocked = await self._run_gated_operation(
                    op, html, doc, ADDITION, text,
                )
            except Exception as exc:
                logger.warning("REDRIVE failed for %r: %s", section, exc)
                continue
            if updated:
                html = updated
                restored_any = True
                logger.info("REDRIVE restored %r after an unrevertable delete", section)
            else:
                logger.warning("REDRIVE could not restore %r", section)
        return html if restored_any else None

    async def _sections_lost_to_revert(self, doc, expected_html: str) -> set[str]:
        """Which sections does `expected_html` still claim that the REMOTE
        no longer has?

        Reads the document's heading outline, which SuperDocs serves free —
        this is the same call the post-batch structural verification already
        makes, so it adds no cost and cannot itself edit anything.

        Returns an empty set on ANY failure. A recovery mechanism that can
        raise is worse than one that occasionally does nothing.
        """
        # The SuperDocs document id, not doc.doc_id — that one is our own
        # internal handle and means nothing to the API.
        durable_id = getattr(self, "_durable_document_id", None)
        if not durable_id or not hasattr(self._client, "get_document_detail"):
            return set()
        try:
            detail = await self._client.get_document_detail(document_id=durable_id)
            remote = {
                html_module.unescape((h.get("text") or "").strip()).lower()
                for h in (detail.get("structure") or {}).get("headings", [])
            }
        except Exception as exc:
            logger.warning("could not read remote structure after revert: %s", exc)
            return set()
        if not remote:
            return set()
        from app.drafting.classifier import _HEADING_RE
        local = {
            html_module.unescape(re.sub(r"<[^>]+>", "", h)).strip()
            for h in _HEADING_RE.findall(expected_html or "")
        }
        return {name for name in local if name and name.lower() not in remote}

    async def _revert_operation(self, doc, turn_index: int) -> bool:
        """Undo ONE operation's remote edit. Returns whether it worked.

        Unlike `_rollback_batch` this surfaces no error and changes no
        status: a single refused operation inside an otherwise good batch is
        not a batch failure, and must not blank the panel.
        """
        if not hasattr(self._client, "revert_session"):
            return True
        for attempt in range(3):
            try:
                await self._client.revert_session(
                    session_id=doc.session_id, turn_index=turn_index
                )
                return True
            except Exception as exc:
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    logger.warning(
                        "operation revert failed — the remote kept this edit, "
                        "so the batch stops here rather than stacking another "
                        "attempt on top of it: %s", exc
                    )
        return False

    async def _run_batch_ops(
        self, ops, all_facts, classification, captured_text, doc, batch
    ) -> str | None:
        """Run a batch's operations, committing each one independently.

        This used to be atomic: any failing operation rolled the WHOLE batch
        back, discarding operations that had already succeeded and ones that
        had not yet run. Live, "PLACEMENT op='Scope of Work' landed=True" was
        followed three operations later by a preservation failure, and the
        finished document was completely empty — the batch destroyed its own
        good work and the reviewer saw a blank template.

        An operation is now the unit of commit. One that fails is reverted on
        its own and the rest carry on. The batch-level retry is gone with it:
        `_run_gated_operation` already retries each operation internally, and
        replaying a whole batch on top of committed operations is how
        duplicate paragraphs appeared.
        """
        original_html = doc.current_draft_html
        current_html = original_html
        committed_facts: list[str] = []
        # (section, fact) for everything committed so far in THIS batch. A
        # revert is issued with a turn index we compute locally, and that
        # number is a guess at SuperDocs' own turn numbering — we increment
        # it on every chat_async, including attempts our gate rejected and
        # that never applied. Guess high and the revert rewinds past
        # operations that had already succeeded, so these have to be
        # recoverable.
        committed_pairs: list[tuple[str | None, str]] = []
        failures: list[str] = []
        # Counted, not inferred from an HTML diff: an operation can
        # legitimately produce identical HTML, and treating that as "nothing
        # landed" reported successful batches as total failures.
        committed = 0
        # A partial failure has to survive _handle_batch's "clear transient
        # error on success" step, or the panel reports a batch that dropped a
        # section as a clean success.
        self._batch_partial_error = None

        for op in ops:
            op_turn = self._turn_count
            op_html = current_html
            foreign_tokens = foreign_fact_tokens(op.facts, all_facts)
            updated, blocked = await self._run_gated_operation(
                op, current_html, doc, classification,
                captured_text, foreign_tokens, all_facts,
            )
            label = op.table_field or op.section or "unrouted"

            if blocked:
                # Integrity block — the panel's blocking card is the outcome
                # and it needs a human, so stop the batch here.
                return None

            if updated is None:
                reason = self._failed_batch_holder or "gated operation failed"
                self._failed_batch_holder = None
                if op.table_field is not None:
                    # A details-table cell is metadata, not the deliverable.
                    logger.warning(
                        "table fill for %r skipped (non-fatal): %s", op.table_field, reason
                    )
                    continue
                failures.append(f"{label}: {reason}")
                # Owed, not lost: this content was asked for and never
                # arrived. Recording it is what lets reconciliation see it —
                # the ledger only ever holds what really landed.
                #
                # Not when the session is unrecoverable, though. That flag
                # means the remote state is UNKNOWN — the commonest cause is
                # an approval SuperDocs accepted whose job never settled for
                # us, so the edit may well be in the document. Re-driving
                # content that is already there duplicates it, which is a
                # worse document than the one with a gap.
                if op.section is not None and not self._unrecoverable:
                    doc.unlanded_facts.extend((op.section, f) for f in op.facts)
                if self._unrecoverable:
                    # 409 or a post-approval divergence: the remote session
                    # is in an unknown state, so issue no further calls —
                    # but keep whatever already committed.
                    break
                # NO revert here. Nothing was applied: the gate denied the
                # proposal and _run_gated_operation already drove the denied
                # job terminal before returning. Reverting anyway is what
                # killed a live meeting — the revert 409s against a session
                # that has just settled a denial, and every subsequent
                # chat_async then 409s too:
                #
                #   GATE REJECT ... missing anchors: ['e-mail', 'small']
                #   POST /sessions/.../revert            409  x3
                #   POST /chat/async                     409  x3   <- wedged
                #
                # A revert belongs only where an edit was actually APPLIED and
                # then failed a post-application check, which is handled below.
                continue

            preserved, missing = facts_preserved_in_html(committed_facts, updated)
            reason = None
            if not preserved:
                reason = f"operation dropped previously committed content: {missing[:5]}"
            elif op.section is not None:
                landed, missing_here = content_landed_in_section(
                    updated, op.section, op.facts
                )
                logger.info(
                    "PLACEMENT op=%r landed=%s missing=%s",
                    op.section, landed, missing_here[:5],
                )
                if not landed:
                    reason = (
                        f"operation targeted '{op.section}' but content landed "
                        f"elsewhere: {missing_here[:5]}"
                    )

            if reason is not None:
                failures.append(f"{label}: {reason}")
                if not await self._revert_operation(doc, op_turn):
                    # The remote KEPT this edit. Its content is in the
                    # document right now, whatever our local copy thinks —
                    # so it must NOT be recorded as owed. Doing that put a
                    # second copy of the Project Details table into a live
                    # document: the operation applied, our post-hoc check
                    # rejected it, the revert 400'd, and reconciliation then
                    # dutifully re-drove content that had never left.
                    #
                    # Owed means "asked for and never arrived". An edit the
                    # remote is still holding has arrived.
                    #
                    # What IS recoverable is the content this edit deleted.
                    # `facts_preserved_in_html` has just proved those facts
                    # are absent from the HTML SuperDocs itself returned, so
                    # re-adding them cannot duplicate anything — that proof
                    # is exactly what the Project Details case lacked.
                    #
                    # This is the run-to-run failure: one batch carries both
                    # Scope of Work and Timeline & Milestones, Scope commits,
                    # the Timeline edit deletes Scope's paragraph, and the
                    # revert answers 400 or 404. Without this, Scope is lost
                    # on every single run.
                    remote_text = _norm_text(updated)
                    dropped = [
                        (sec, f) for sec, f in committed_pairs
                        if sec is not None and not _fact_still_present(f, remote_text)
                    ]
                    # The remote kept this edit, so `updated` — not op_html —
                    # is what the document actually holds. Adopting it keeps
                    # the panel honest and lets the re-drive below build on
                    # the real state.
                    current_html = updated
                    doc.current_draft_html = updated
                    if dropped:
                        restored = await self._redrive_dropped(
                            doc, dropped, classification
                        )
                        if restored:
                            current_html = restored
                            doc.current_draft_html = restored
                    break
                # Reverted cleanly, so the content really is gone now and
                # reconciliation should get it back.
                if op.section is not None:
                    doc.unlanded_facts.extend((op.section, f) for f in op.facts)
                current_html = op_html
                doc.current_draft_html = op_html
                # The revert may have taken more than it was asked to.
                # Reconcile it against what the remote ACTUALLY has — a free
                # structure read, never billed — instead of trusting
                # op_html. Local silently disagreeing with the remote is the
                # worst of the three outcomes: the panel shows content that
                # is gone, and reconciliation, which compares against local,
                # sees nothing missing and does nothing.
                lost = await self._sections_lost_to_revert(doc, op_html)
                if lost:
                    logger.warning(
                        "REVERT OVERREACH: %s vanished from the remote while "
                        "undoing %r — re-driving their content",
                        sorted(lost), label,
                    )
                    current_html = _drop_sections(op_html, lost)
                    doc.current_draft_html = current_html
                    doc.unlanded_facts.extend(
                        (sec, f) for sec, f in committed_pairs if sec in lost
                    )
                    committed_pairs = [
                        (sec, f) for sec, f in committed_pairs if sec not in lost
                    ]
                    committed_facts = [f for _, f in committed_pairs]
                continue

            committed_facts.extend(op.facts)
            committed_pairs.extend((op.section, f) for f in op.facts)
            committed += 1
            current_html = updated
            doc.current_draft_html = current_html

        if committed == 0:
            # Nothing landed at all — there is no partial result to publish.
            self._failed_batch = batch
            self.error = f"batch failed: {failures[0] if failures else 'no operation succeeded'}"
            await self._publish({"type": "error", "message": self.error})
            await self._set_status(STATUS_ERROR)
            return None

        ok_struct, sreason = await self._verify_structure(doc)
        if not ok_struct:
            # Structural damage is document-level, not operation-level: the
            # template itself is wrong now, so the whole batch goes back.
            await self._rollback_batch(
                doc, self._turn_count, original_html, batch, f"structure: {sreason}"
            )
            return None

        if failures:
            # Partial success. The document keeps what landed and the panel
            # says what did not — reporting this as a clean success would
            # hide a missing section from the reviewer.
            logger.warning("BATCH PARTIAL: %d operation(s) failed: %s", len(failures), failures[:3])
            self._batch_partial_error = f"some content could not be added: {failures[0]}"
            self.error = self._batch_partial_error
            await self._publish({"type": "error", "message": self.error})

        return current_html

    async def _run_gated_operation(
        self,
        op,
        draft_html: str,
        doc,
        classification: str,
        captured_text: str,
        foreign_tokens: list[str] | None = None,
        all_facts: list[str] | None = None,
    ) -> tuple[str | None, bool]:
        """Thin wrapper around `_run_gated_operation_impl`: publishes which
        section is actively being worked on for the duration of the call,
        so the panel can show "drafting…" against the real target instead
        of the whole 9-heading skeleton up front. Cleared on every exit
        path (success, failure, or block) via finally — never left stale."""
        self.active_section = op.section
        await self._publish({"type": "active_section", "section": self.active_section})
        try:
            return await self._run_gated_operation_impl(
                op, draft_html, doc, classification, captured_text, foreign_tokens, all_facts,
            )
        finally:
            self.active_section = None
            await self._publish({"type": "active_section", "section": None})

    async def _run_gated_operation_impl(
        self,
        op,
        draft_html: str,
        doc,
        classification: str,
        captured_text: str,
        foreign_tokens: list[str] | None = None,
        all_facts: list[str] | None = None,
    ) -> tuple[str | None, bool]:
        """One section operation through the gate: ask_every_time → inspect
        pending_changes → deterministic validation → approve or deny. Returns
        (updated_html, blocked) — blocked=True means an integrity block is
        the outcome (blocking card shown); None means the operation failed
        and the caller must roll the batch back."""
        from app.drafting.classifier import CORRECTION, correction_values

        last_failure = ""
        # Structural rejections (placeholder/heading/table) indicate the
        # model is emitting template-filler markup, not converging — give it
        # at most one explicit-constraint retry, then fail the operation
        # (the batch retry may still succeed on a fresh run). Non-structural
        # rejections keep the full 3-attempt budget.
        max_attempts = 3
        for attempt in range(max_attempts):
            # Retry = a fresh instruction carrying the validation failure as
            # a revision note — the documented agent pattern (re-send with
            # the instruction rewritten), not dependence on an in-job
            # revision the platform only sometimes produces.
            message = op.instruction
            if attempt > 0:
                target = op.section or "the most appropriate section"
                message = (
                    op.instruction
                    + f"\n\nREVISION NOTE: the previous attempt was rejected because: {last_failure}. "
                    + f"Apply ONLY to {target}. Preserve headings and structure. "
                    + "Do not add new tables or sections."
                )
                if _is_structural_failure(last_failure):
                    # Explicit constraint against the exact defect. The
                    # "unsupported content" case needs its own explicit
                    # language: observed live, repeatedly, across several
                    # operations — rejected for inventing facts, the model's
                    # retry doesn't add new FACTS, it pads the same true
                    # fact with unrequested descriptive/framing words
                    # ("a professional website", "a secure payment
                    # integration system", "This project involves a website
                    # development engagement") that are just as ungrounded
                    # as an invented fact, and the generic "never invent
                    # facts" wording doesn't register with it as covering
                    # adjectives and framing, only nouns/numbers.
                    message += (
                        "\n\nSTRUCTURAL CONSTRAINT: never emit heading markup, "
                        "placeholder/filler text such as 'Please fill:', TBD, TODO, "
                        "or any new table. Write the fact as a plain paragraph only."
                    )
                    if "unsupported content" in last_failure:
                        message += (
                            "\n\nWORDING CONSTRAINT: use ONLY the words and values given "
                            "above. Do not add descriptive adjectives, business framing, "
                            "or elaboration not present in the source — no 'professional', "
                            "'secure', 'engagement', 'seamless', or similar. Write the "
                            "shortest possible correct sentence stating the fact plainly."
                        )
            await self._set_status(STATUS_SENDING)
            try:
                job = await self._client.chat_async(
                    message=message,
                    session_id=doc.session_id,
                    approval_mode="ask_every_time",
                    model_tier=self._model_tier,
                    thinking_depth=self._thinking_depth,
                )
                self._turn_count += 1
            except Exception as exc:
                # A 409 Conflict means the remote session is in a state that
                # rejects this call — no retry will fix it, only the rollback
                # (and possibly a full revert) can. Fail the op AND mark the
                # batch unrecoverable so the batch loop does not re-submit.
                if _is_conflict(exc):
                    self._failed_batch_holder = f"SuperDocs conflict: {exc}"
                    self._unrecoverable = True
                    return None, False
                if attempt < 2:
                    await self._publish(
                        {"type": "error", "message": f"Retrying ({attempt + 1}/3)…"}
                    )
                    await asyncio.sleep(2 ** attempt)
                    continue
                self._failed_batch_holder = str(exc)
                return None, False

            await self._set_status(STATUS_POLLING)
            settled = await self._poll_job_until(
                job.job_id, ("awaiting_approval", "completed", "failed", "cancelled")
            )
            if settled is None:
                self._failed_batch_holder = "job did not settle"
                return None, False

            if settled.status != "awaiting_approval":
                if settled.status == "completed" and settled.document_changes is not None:
                    updated = _strip_empty_sections(
                        settled.document_changes.updated_html or draft_html
                    )
                    # SuperDocs applied this itself instead of offering it for
                    # approval, so the proposal gate never saw it. Without this
                    # the auto-apply path was an unguarded hole straight into
                    # the document: a real export came back carrying "Please
                    # fill:" placeholders, a second Project Details table, and
                    # four rephrased copies of one sentence.
                    defect = structural_defect(draft_html, updated)
                    if defect is not None:
                        self._failed_batch_holder = f"auto-applied edit rejected: {defect}"
                        return None, False
                    result = check_integrity(
                        html_before=draft_html,
                        html_after=updated,
                        changes=[d.model_dump() for d in settled.document_changes.changes],
                        classification=classification,
                    )
                    if result.passed:
                        return updated, False
                    await self._set_blocked(classification, captured_text, draft_html, updated, result.reason)
                    return None, True  # integrity block
                self._failed_batch_holder = "SuperDocs reported the edit failed."
                return None, False

            # GATE — inspect the proposal, decide, approve or deny.
            changes = settled.metadata.pending_changes
            if not changes:
                try:
                    await self._client.approve_changes(
                        session_id=doc.session_id, job_id=job.job_id, approved=False
                    )
                except Exception:
                    pass
                self._failed_batch_holder = "SuperDocs returned no proposed changes"
                return None, False

            failures: list[str] = []
            ok = True
            for change in changes:
                if op.table_field is not None:
                    good, fails = validate_table_fill(op, change)
                elif op.is_correction:
                    expected_old, expected_new = correction_values(captured_text, draft_html)
                    good, fails = validate_correction(
                        op, change, draft_html, expected_old, expected_new
                    )
                else:
                    good, fails = validate_proposal(
                        op, change, draft_html, foreign_tokens, all_facts
                    )
                ok = ok and good
                failures.extend(fails)

            if ok:
                try:
                    await self._client.approve_changes(
                        session_id=doc.session_id,
                        job_id=job.job_id,
                        approved=True,
                        changes=[
                            {"change_id": c.change_id, "approved": True} for c in changes
                        ],
                    )
                except Exception as exc:
                    self._failed_batch_holder = str(exc)
                    if _is_conflict(exc):
                        # The approve call itself conflicted — remote state
                        # unknown; do not retry this batch.
                        self._unrecoverable = True
                    return None, False
                settled = await self._poll_job_until(
                    job.job_id, ("completed", "failed", "cancelled")
                )
                if settled is None or settled.status != "completed" or settled.document_changes is None:
                    # approve_changes SUCCEEDED remotely (the changes were
                    # accepted by SuperDocs) but the job never settled
                    # locally. The remote document may have been edited —
                    # do NOT re-submit a fresh chat against this session
                    # (that is what 409s), and do not process later batches
                    # until explicit recovery.
                    self._failed_batch_holder = "edit did not settle after approval"
                    self._unrecoverable = True
                    return None, False
                updated = _strip_empty_sections(
                    settled.document_changes.updated_html or draft_html
                )
                result = check_integrity(
                    html_before=draft_html,
                    html_after=updated,
                    changes=[d.model_dump() for d in settled.document_changes.changes],
                    classification=classification,
                )
                if not result.passed:
                    await self._set_blocked(classification, captured_text, draft_html, updated, result.reason)
                    return None, True
                return updated, False

            # Rejected — deny (with feedback for the platform's records) and
            # retry with a tightened instruction on the next attempt.
            last_failure = failures[0]
            logger.warning(
                "GATE REJECT attempt=%d op=%s failures=%s chunk=%s",
                attempt + 1, op.section, failures, [c.chunk_id for c in changes],
            )
            if _is_structural_failure(last_failure) and attempt >= 1:
                # Same structural defect twice — the instruction needs a
                # rewrite, not another model call. Fail the operation so the
                # batch retry (fresh run) or the error path takes over.
                # Never bypasses validation; never exposes a partial batch.
                try:
                    await self._client.approve_changes(
                        session_id=doc.session_id,
                        job_id=job.job_id,
                        approved=False,
                        changes=[{"change_id": c.change_id, "approved": False} for c in changes],
                        feedback=f"Rejected: {failures[0]}",
                    )
                except Exception:
                    pass
                # Settle the denied job before the batch retry issues a fresh
                # chat — leaving it open is exactly what makes that chat 409.
                await self._settle_denied_job(job.job_id)
                self._failed_batch_holder = (
                    f"validation rejected on structural defect twice: {last_failure}"
                )
                return None, False
            try:
                await self._client.approve_changes(
                    session_id=doc.session_id,
                    job_id=job.job_id,
                    approved=False,
                    changes=[{"change_id": c.change_id, "approved": False} for c in changes],
                    feedback=f"Rejected: {failures[0]}",
                )
            except Exception as exc:
                self._failed_batch_holder = str(exc)
                if _is_conflict(exc):
                    self._unrecoverable = True
                return None, False
            # The deny was accepted but the job is not finished — the same
            # asymmetry already solved for approve(True), which polls. Drive
            # the denied job to terminal before the next chat_async, or the
            # still-open job makes that chat 409 (the denial wedge).
            if not await self._settle_denied_job(job.job_id):
                # A timeout is not a conflict. A 409 means the remote state
                # is genuinely broken and every further call will fail; a
                # settle timeout usually means the platform is just slow.
                # Treating them alike made one sluggish denial cost the
                # whole meeting — four benchmark runs died here with a
                # single batch committed and an empty document, while the
                # remaining transcript was simply discarded. Fail this
                # batch; later batches still get their turn, and if the
                # unfinished job really does wedge the session the 409 path
                # below catches it and queues the rest for Retry.
                self._failed_batch_holder = "denied job did not settle"
                return None, False

        self._failed_batch_holder = (
            f"validation rejected every attempt (3): {last_failure}"
        )
        return None, False

    async def _set_blocked(
        self, classification: str, captured_text: str, html_before: str, html_after: str, reason: str | None
    ) -> None:
        """Surface the integrity blocking card — the one place this state
        is created, so every path that fails integrity behaves identically."""
        self._pending_blocked = {
            "classification": classification,
            "text": captured_text,
            "html_before": html_before,
            "html_after": html_after,
            "reason": reason,
            "timestamp": time.time(),
        }
        await self._set_status(STATUS_BLOCKED)
        await self._publish(
            {
                "type": "blocking_card",
                "reason": reason,
                # The utterance that was blocked. A reason on its own ("a
                # correction batch touched 5 chunks") tells the reviewer a
                # rule fired, not what they are being asked to decide.
                "text": captured_text,
                "html_before": html_before,
                "html_after": html_after,
            }
        )

    async def _rollback_batch(
        self, doc, turn_base: int, original_html: str, batch, reason: str
    ) -> bool:
        """Restore the pre-batch state after a failed batch. Reverts the
        session server-side (escape hatch — not the normal path) and restores
        the local draft, then surfaces an error. Never exposes a partial
        batch as the final result.

        Returns whether the SERVER-SIDE rewind succeeded. It matters: when
        the revert fails, the rejected content is still in the remote
        document while the local draft is restored as if it were not. The
        panel then shows a clean draft, the export pulls the polluted remote
        copy, and every retry of the batch adds another variant of the same
        paragraph — one real export carried the Deliverables sentence eight
        times over, in eight phrasings, because each retry landed remotely
        and nothing local ever knew."""
        reverted = True
        if hasattr(self._client, "revert_session"):
            reverted = False
            # Revert can 409 while the last denied job is still settling —
            # retry briefly before giving up on the server-side rewind.
            for _attempt in range(3):
                try:
                    await self._client.revert_session(
                        session_id=doc.session_id, turn_index=turn_base
                    )
                    reverted = True
                    break
                except Exception as exc:
                    if _attempt < 2:
                        await asyncio.sleep(2)
                    else:
                        logger.warning(
                            "revert failed during rollback — local and remote have "
                            "diverged, not retrying this batch: %s", exc
                        )
        if reverted:
            doc.current_draft_html = original_html
        else:
            # The remote was NOT rewound, so it still holds this batch's
            # edits. Restoring the local copy to the pre-batch state here is
            # what made the divergence this method's docstring warns about
            # visible to the user: the panel showed an empty document while
            # the real one had content, and the export pulled the remote
            # copy the reviewer had never seen. Keeping the last locally
            # verified state is strictly closer to the truth — it is the
            # content that actually landed AND passed the gate, and it never
            # throws away good work to undo one bad operation.
            # Retaining content is only safe if the content is clean. When
            # SuperDocs applies an edit itself instead of offering it for
            # approval, a proposal this gate REJECTED can already be in the
            # remote document — live, three placeholder rejections still left
            # "Please fill: October [Day], 2026" in Timeline. Keeping that and
            # publishing it as an approvable version would hand the reviewer,
            # as reviewable work, the exact text the gate just refused. If the
            # retained draft is defective, take the empty document instead:
            # losing the batch is recoverable, approving filler is not.
            defect = structural_defect(original_html, doc.current_draft_html)
            if not defect:
                # structural_defect covers placeholders, new tables and
                # duplicated prose, but not an INVENTED heading — and the
                # platform produces those too. Live, a failed batch left
                # "## Scope of Work. The project is for Star Goods, a small
                # e-commerce company..." appended as a heading of its own,
                # and retaining it published a mangled document as reviewable
                # work. _verify_structure applies this same rule, but only on
                # batches that succeed; a retained draft needs it too.
                allowed = set(template_sections(doc.template_key))
                for heading in _draft_headings(doc.current_draft_html):
                    if heading not in allowed and heading not in _draft_headings(original_html):
                        defect = f"retained draft has an invented heading: {heading[:60]!r}"
                        break
            if defect:
                logger.warning(
                    "remote was not rewound AND the retained draft is "
                    "defective (%s) — falling back to the pre-batch draft", defect
                )
                doc.current_draft_html = original_html
                self._failed_batch = batch
                self.error = f"batch failed: {reason}"
                await self._publish({"type": "error", "message": self.error})
                await self._set_status(STATUS_ERROR)
                return reverted
            # Retaining is only worth a version bump if something is actually
            # retained. A batch that failed before anything landed leaves the
            # draft exactly as it started, and bumping anyway published an
            # approvable, exportable version of an EMPTY document — live, the
            # panel showed "v2" over a template with every section blank.
            if len(_norm_text(doc.current_draft_html)) <= len(_norm_text(original_html)):
                logger.warning(
                    "remote was not rewound but nothing was retained — "
                    "leaving the draft version unchanged"
                )
                self._failed_batch = batch
                self.error = f"batch failed: {reason}"
                await self._publish({"type": "error", "message": self.error})
                await self._set_status(STATUS_ERROR)
                return reverted
            logger.warning(
                "remote was not rewound — keeping the last verified local "
                "draft rather than showing an empty document"
            )
            # Keeping the content is only half of it. draft_version is what
            # the review gate approves against, and it is bumped solely on a
            # fully successful batch — so retained content sat at version 0
            # and the reviewer could see a populated document with nothing
            # approvable and nothing exportable. Publish it as a real version:
            # it is content that passed the gate and is genuinely in the
            # remote document, so it is reviewable work, and the error below
            # still tells them the batch behind it failed.
            doc.draft_version += 1
            await self._publish({
                "type": "draft_updated",
                "html": doc.current_draft_html,
                "draft_version": doc.draft_version,
            })
        self._failed_batch = batch
        self.error = f"batch failed: {reason}"
        await self._publish({"type": "error", "message": self.error})
        await self._set_status(STATUS_ERROR)
        return reverted

    async def _verify_structure(self, doc) -> tuple[bool, str]:
        """Free structure read after a batch: the template's headings must
        still exist unchanged. Skipped when the client/fake has no structure
        endpoint or no durable document id is known."""
        durable_id = getattr(self, "_durable_document_id", None)
        if not durable_id or not hasattr(self._client, "get_document_detail"):
            return True, ""
        from app.drafting.classifier import _draft_headings
        try:
            detail = await self._client.get_document_detail(document_id=durable_id)
        except Exception as exc:
            return False, f"structure read failed: {exc}"
        structure = detail.get("structure") or {}
        remote_headings = [
            html_module.unescape((h.get("text") or "").strip())
            for h in structure.get("headings", [])
        ]
        local_headings = _draft_headings(doc.current_draft_html)
        # Local is ALLOWED to be missing headings the remote still has, and an
        # equal-length comparison here was wrong about that. `_strip_empty_sections`
        # drops unsupported sections from our copy the moment a batch lands, while
        # the remote keeps them until `_cleanup_empty_sections_before_export`
        # reconciles at export. That divergence is the design — this check simply
        # never saw it, because the stripper's regex demanded a bare <h2> and so
        # matched nothing SuperDocs had ever touched. Fixing the stripper made the
        # contradiction real and failed every batch that stripped anything.
        #
        # What must still hold, and what each clause below catches:
        #   - every local heading survives remotely, unchanged and in order
        #     (SuperDocs mangling, deleting or reordering our headings)
        #   - anything remote-only is a section THIS template defines, never one
        #     SuperDocs invented (the observed "invented table"/retitling failures)
        allowed_extra = set(template_sections(doc.template_key))
        remaining = list(remote_headings)
        for lh in local_headings:
            while remaining and remaining[0] != lh:
                dropped = remaining.pop(0)
                if dropped not in allowed_extra:
                    return False, f"unexpected remote heading: {dropped!r}"
            if not remaining:
                return False, f"heading missing remotely: {lh!r}"
            remaining.pop(0)
        for extra in remaining:
            if extra not in allowed_extra:
                return False, f"unexpected remote heading: {extra!r}"
        return True, ""

    async def _initialize_document(self) -> None:
        doc = self._active_doc
        if doc.custom_template_b64:
            # The firm's own file, uploaded verbatim — SuperDocs converts it
            # and returns the HTML, so its headings, table and styling are
            # what the drafting then fills in.
            payload = doc.custom_template_b64
            filename = doc.custom_template_name or "template.docx"
        else:
            # Render the active document's actual template, not hardcoded SOW.
            payload = base64.b64encode(
                render_template(
                    doc.template_key,
                    topic=self._template_meta.get("topic", ""),
                    client=self._template_meta.get("client", ""),
                    prepared_by=self._template_meta.get("prepared_by", ""),
                ).encode()
            ).decode()
            filename = "draft.html"
        upload = await self._client.upload_base64(
            file_base64=payload,
            filename=filename,
            session_id=doc.session_id,
            return_html=True,
        )
        self.current_draft_html = upload.html or _BLANK_STARTER_HTML
        self._document_initialized = True
        # Capture the durable document id for the free structure read —
        # available immediately after upload (proven in capability
        # experiments E3). Best-effort: fakes and odd states skip it.
        if hasattr(self._client, "get_session_documents"):
            try:
                docs = await self._client.get_session_documents(session_id=self._active_doc.session_id)
                for d in docs:
                    if d.get("durable_document_id"):
                        self._durable_document_id = d["durable_document_id"]
                        break
            except Exception as exc:
                logger.warning("could not resolve durable document id: %s", exc)
        # draft_version stays 0 here, deliberately — the blank starter isn't
        # a version anyone would ever review or export.
        await self._publish(
            {"type": "draft_updated", "html": self.current_draft_html, "draft_version": self.draft_version}
        )

    async def _poll_job_until(self, job_id: str, statuses: tuple[str, ...]):
        """Poll a job until its status is one of `statuses`, or None on
        deadline. Returns the settled job."""
        deadline = time.time() + _JOB_POLL_DEADLINE_SECONDS
        while time.time() < deadline:
            job = await self._client.get_job(job_id)
            if job.status in statuses:
                return job
            await asyncio.sleep(self._poll_interval_seconds)
        return None

    async def _settle_denied_job(self, job_id: str) -> bool:
        """Drive a denied job to a terminal state so the session releases
        its lock. approve_changes(approved=False) returns 200 but — like an
        approval — does not finish the job; the approve path polls after
        approved=True and the deny path must too, or the next chat_async 409s
        on the still-open job. Returns True when the job reached a terminal
        state within the poll deadline."""
        settled = await self._poll_job_until(job_id, ("completed", "failed", "cancelled"))
        return settled is not None

    async def _poll_job(self, job_id: str):
        job = await self._poll_job_until(job_id, ("completed", "failed", "cancelled", "awaiting_approval"))
        if job is None:
            raise TimeoutError(f"job {job_id} did not settle within {_JOB_POLL_DEADLINE_SECONDS:.0f}s")
        return job

    async def _set_status(self, status: str) -> None:
        self.job_status = status
        await self._publish({"type": "job_status", "status": status})

    # ---- panel-facing state -------------------------------------------------

    def state_snapshot(self) -> dict:
        snapshot = {
            "meeting_uuid": self.meeting_uuid,
            "job_status": self.job_status,
            "error": self.error,
            "current_draft_html": self.current_draft_html,
            "transcript_history": [e.model_dump() for e in self.transcript_history],
            "activity": self.activity,
            "draft_version": self.draft_version,
            "approved_draft_version": self.approved_draft_version,
            "approved_by": self.approved_by,
            "export_ready": self.export_ready,
            "last_export": (
                {
                    "content_type": self.last_export.content_type,
                    "size": len(self.last_export.content),
                    "exported_at": self.last_export_at,
                    "exported_by": self.exported_by,
                }
                if self.last_export is not None
                else None
            ),
            "active_document_id": self._active_doc.doc_id,
            "active_template_key": self._active_doc.template_key,
            "documents": self._document_list(),
            "helper_status": self.helper_status,
            "helper_connected": self.helper_connected,
            "active_section": self.active_section,
            "pending_batches": len(self._pending_batches),
            "custom_template_name": self._active_doc.custom_template_name,
            # A blocking card used to exist ONLY as a transient event. Live,
            # a correction was approved on SuperDocs, failed our integrity
            # check, and left the server on job_status="blocked" with
            # error=None — while any panel that reloaded (or joined late)
            # rebuilt its state from here, found nothing, and rendered a
            # healthy session. The remote document held an edit the panel
            # never showed and no card ever asked about. State that needs a
            # human has to survive a reload, so it belongs in the snapshot.
            # html_before/html_after are deliberately NOT included: this is
            # polled continuously and the card only ever displays `reason`.
            "blocking_card": (
                {
                    "reason": self._pending_blocked["reason"],
                    "text": self._pending_blocked["text"],
                    "classification": self._pending_blocked["classification"],
                    "timestamp": self._pending_blocked["timestamp"],
                }
                if self._pending_blocked is not None
                else None
            ),
        }
        if self.manual_provider is not None:
            snapshot["provider"] = {
                "name": self.manual_provider.name,
                "status": self.manual_provider.status(),
            }
        return snapshot

    # ---- Milestone 5: review/export gate -------------------------------------
    #
    # A pure in-house state machine — deliberately never calls
    # SuperDocsClient.approve(). PROGRESS.md M1 found that endpoint
    # unreliable (the job stayed awaiting_approval and export kept returning
    # the pre-edit document); every batch here already runs
    # approval_mode="auto", so nothing is ever awaiting SuperDocs-side
    # approval in the first place. approve_draft() is named distinctly from
    # SuperDocsClient.approve() on purpose, so the two are never confused.

    @property
    def export_ready(self) -> bool:
        """True exactly when the CURRENT draft is the one approve_draft()
        last approved. Derived, not stored — a stored boolean would need
        its own invalidation wired into every place the draft can change,
        exactly the kind of parallel bookkeeping that can drift out of
        sync. Comparing two ints can't desync from itself."""
        return (
            self.approved_draft_version is not None
            and self.approved_draft_version == self.draft_version
        )

    def changes_since_approval(self) -> list[dict]:
        """activity[i] is exactly what got appended when draft_version moved
        from i to i+1 (both only change together, in _handle_batch's success
        block) — so this slice is exact, not approximate, and never invents
        a field this codebase doesn't track (IntegrityResult has no
        structured before/after value anywhere to draw one from). A None
        approved_draft_version slices from the start for free — "everything
        so far" needs no special-casing."""
        return self.activity[self.approved_draft_version : self.draft_version]

    async def approve_draft(self, *, draft_version: int, approver: str | None = None) -> None:
        """Raises ValueError — not a silent no-op — the instant the
        caller's draft_version no longer matches current state: the
        server-side guard against approving content the user never
        actually saw (a batch can land between the review screen
        rendering and the user clicking Approve).

        `approver` is self-reported (the Zoom participant's screenName from
        the client) — attribution, not authentication, same trust level as
        every other field this app already takes from the Zoom SDK context."""
        if draft_version != self.draft_version:
            raise ValueError(
                f"draft has moved to version {self.draft_version} since you reviewed "
                f"version {draft_version} — refresh and review again before approving"
            )
        self.approved_draft_version = draft_version
        self.approved_by = approver or None
        await self._publish({
            "type": "draft_approved",
            "draft_version": draft_version,
            "approved_by": self.approved_by,
        })

    async def _cleanup_empty_sections_before_export(self, doc) -> None:
        """Best-effort: bring the REMOTE document SuperDocs holds in line
        with what the panel already shows locally. export() pulls
        SuperDocs' own remote document — it never receives the local
        `_strip_empty_sections` cleanup the panel applies to its own copy
        — confirmed live: an exported document carried template-filler
        headings (Executive Summary, Objectives, ...) with zero content
        the panel itself never displayed as anything but empty/dimmed.

        Deliberately the narrowest possible trust: only ever approves a
        change if EVERY proposed edit is a pure removal (empty new_html) —
        anything that looks like a rewrite instead of a delete is denied
        and the cleanup is silently abandoned. Any failure anywhere —
        timeout, exception, an unexpected proposal shape — is swallowed:
        this step is cosmetic, and export must keep working exactly as it
        always has whether or not this can complete. Never a new way for
        export to fail."""
        empty = _empty_heading_texts(doc.current_draft_html)
        if not empty:
            return
        try:
            message = (
                "Remove ONLY the following section headings and their "
                "(already empty) content from the document. Change nothing "
                "else — do not add, rewrite, or move any other content:\n"
                + "\n".join(f"- {h}" for h in empty)
            )
            job = await self._client.chat_async(
                message=message, session_id=doc.session_id, approval_mode="ask_every_time",
            )
            settled = await self._poll_job_until(
                job.job_id, ("awaiting_approval", "completed", "failed", "cancelled")
            )
            if settled is None or settled.status != "awaiting_approval":
                return
            changes = settled.metadata.pending_changes
            if not changes or any((c.new_html or "").strip() for c in changes):
                if changes:
                    await self._client.approve_changes(
                        session_id=doc.session_id, job_id=job.job_id, approved=False,
                        changes=[{"change_id": c.change_id, "approved": False} for c in changes],
                    )
                    await self._settle_denied_job(job.job_id)
                return
            await self._client.approve_changes(
                session_id=doc.session_id, job_id=job.job_id, approved=True,
                changes=[{"change_id": c.change_id, "approved": True} for c in changes],
            )
            await self._poll_job_until(job.job_id, ("completed", "failed", "cancelled"))
        except Exception as exc:
            logger.warning("export cleanup pass failed (non-fatal, exporting as-is): %s", exc)

    async def export_draft(self, *, format: str = "docx", exporter: str | None = None) -> ExportResult:
        """Reuses the existing _inflight_lock — export is a SuperDocs call
        for this session_id exactly like chat_async is, so it belongs in
        the same single-in-flight-call-per-session guarantee, not a new
        concept. Checked twice: once before queuing (fail fast, no reason
        to make an already-stale request wait behind the lock), once again
        right after acquiring it, because an in-flight batch can complete
        and invalidate the approval while this call was waiting its turn —
        the export-side mirror of approve_draft's own race guard. Does NOT
        clear approved_draft_version on success: the brief's invariant is
        "draft changes invalidate approval," never "export invalidates
        approval" — the same approved version can be re-exported (retry a
        failed download, get a second copy) without re-approving, which is
        also what makes "export doesn't end the session" true for free."""
        if not self.export_ready:
            raise ValueError("no approved draft to export")
        async with self._inflight_lock:
            if not self.export_ready:
                raise ValueError("no approved draft to export")
            await self._cleanup_empty_sections_before_export(self._active_doc)
            try:
                result = await self._client.export(session_id=self._active_doc.session_id, format=format)
            except Exception as exc:
                await self._publish({"type": "error", "message": f"export failed: {exc}"})
                raise
            self.last_export = result
            self.last_export_at = time.time()
            self.exported_by = exporter or None
            # Same policy as draft_approved above: real state changed
            # (last_export/last_export_at), so it gets published — the
            # panel's own POST response is not what updates its UI, the SSE
            # echo is, exactly like every other mutation in this class.
            await self._publish(
                {
                    "type": "export_completed",
                    "content_type": result.content_type,
                    "size": len(result.content),
                    "exported_at": self.last_export_at,
                    "exported_by": self.exported_by,
                }
            )
            return result

    async def _publish(self, event: dict) -> None:
        for queue in list(self._subscribers):
            await queue.put(event)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)


# ---- registry: one MeetingSession per meeting, in-memory (M0 decision 3) ----

_sessions: dict[str, MeetingSession] = {}


async def get_or_create_session(meeting_uuid: str, client: SuperDocsClient) -> MeetingSession:
    session = _sessions.get(meeting_uuid)
    if session is not None:
        return session
    # Milestone 4: the one place TRANSCRIPT_PROVIDER gets read. manual_provider
    # is set whenever the chosen provider supports manual override input —
    # true for both concrete providers today (Manual always; RTMSTranscript-
    # Provider as its own fallback-without-restarting mechanism, see its
    # module docstring) — generalizing past an isinstance list so a future
    # provider only needs a submit() method, not a registry update here.
    provider = create_transcript_provider(get_settings())
    manual_provider = provider if hasattr(provider, "submit") else None
    session = MeetingSession(meeting_uuid, client, provider, manual_provider=manual_provider)
    _sessions[meeting_uuid] = session
    await session.start()
    return session


def get_session(meeting_uuid: str) -> MeetingSession | None:
    return _sessions.get(meeting_uuid)
