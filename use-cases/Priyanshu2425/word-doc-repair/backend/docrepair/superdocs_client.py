"""The styling pass: the path that produces the file the product promises.

The brief for this build is explicit about what a strong result looks like — a
reviewer runs a broken DOCX through the tool and "gets a valid, **styled** file
back with a clear summary of what was recovered". So this is not a ceiling on
top of the local rebuild; it is the main road. The local rebuild is what gets
sent, and what the person still gets if this road is closed.

The call sequence, against the documented endpoints:

  1. POST /v1/documents/upload   multipart file + session_id
                                  -> loads the rebuilt .docx as the session's
                                     active editable document. Parsing is not
                                     billable; images are extracted to cloud
                                     storage and referenced by URL, which is why
                                     the pictures survive without a separate
                                     image call.
  2. POST /v1/chat               {message, session_id}
                                  -> synchronous: the AI applies the edit inline
                                     and the change is live on the session when
                                     the call returns.
  3. POST /v1/documents/export   {session_id, format:"docx"}
                                  -> round-trips through the original docx
                                     renderer, preserving tables, borders,
                                     shading, headers, footers, fonts, inline
                                     styling and embedded images.

On the approval step
--------------------
The task brief names a four-call minimum contract: upload, chat, approve,
export. This build makes three of them, deliberately and on the product owner's
instruction: the synchronous `/v1/chat` endpoint applies its change inline, and
the documented approval endpoint (`POST /v1/chat/{session_id}/approve`) exists
only on the asynchronous `chat_async` path, reached by setting
`approval_mode='ask_every_time'` and polling to `awaiting_approval`. Adding it
would mean moving to the async flow purely to have something to approve. The
decision recorded for this build is to trust the model on a formatting-only
instruction and to verify the *result* instead — see `_why_not_acceptable`,
which refuses a styled file that came back with fewer pictures or different
words than the one that was sent. Verification after the fact is doing the work
approval-before-the-fact would have done, on the thing that actually ships.

Prompting for styling
---------------------
The instruction is bounded on purpose. This document was reconstructed from
damage and its text is the only record of what its owner wrote, so the edit is
allowed to change how it looks and nothing else.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import requests

# -- where a request goes, and who it goes as ---------------------------------
#
# There are two ways to reach SuperDocs, and choosing between them is a
# security position rather than a convenience. Somebody who has their own key
# sends it to SuperDocs' own origin, where it never touches infrastructure a
# third party operates and logs. Somebody who has no key at all still gets a
# styling pass, because relay -- a small deployed worker that holds a key and
# lends it out under a daily ration -- stands in for one. What that costs is
# the ration and somebody else's logs, which is a fair price for not having to
# sign up before finding out whether this thing salvages your document.
#
# Relay's SuperDocs base is a drop-in replacement: every path below is
# unchanged, so this is a base-and-key swap and nothing more.

#: SuperDocs' own origin -- where a request goes the moment a key exists to
#: send it with.
SUPERDOCS_ORIGIN = "https://api.superdocs.app"

#: This module's older published name for the origin, from when there was
#: nowhere else a request could go. Nothing on the request path reads it any
#: more -- every call is built on `self.base` -- and it is kept only so an
#: importer that reached for it still finds the origin.
BASE = SUPERDOCS_ORIGIN

#: Relay's defaults, committed on purpose. `RELAY_KEY` is not a secret: it is
#: the thing that makes `cp .env.example .env` enough to run this build.
RELAY_URL = "https://relay.pxyz943.workers.dev"
RELAY_KEY = "pk_f2a01b7f189f0d1ea6c57a04cb83c14e"
#: Relay's SuperDocs mount. `/v1/...` continues underneath it unchanged.
RELAY_SUPERDOCS_PATH = "/v1/superdocs"

#: What relay lends out, per key per day. It charges for `/v1/chat`,
#: `/v1/chat/async` and re-edits only; uploads, exports, job polls, session
#: reads and `whoami` are free -- the same shape as SuperDocs' own metering,
#: which is why the ration below fits inside `Allowance` rather than sitting
#: beside it as a second, parallel notion of "no more".
RELAY_DAILY_OPERATIONS = 460
#: Relay refuses a request body larger than this. Named in the message rather
#: than guessed at: somebody whose 12 MB document was turned away needs to
#: know it was the size, and that their own key carries no such ceiling.
RELAY_MAX_REQUEST_BYTES = 8 * 1024 * 1024

log = logging.getLogger("superdocs")


class NotConfigured(RuntimeError):
    """No way to reach SuperDocs at all: no key of one's own, and no relay."""


@dataclass(frozen=True)
class Endpoint:
    """Where requests go, what they go as, and whether that is relay.

    `available` is false only when nothing whatsoever is configured -- the one
    case this build has always degraded to the plain rebuild for.
    """

    base_url: str = SUPERDOCS_ORIGIN
    api_key: str = ""
    using_relay: bool = False

    @property
    def available(self) -> bool:
        return bool(self.api_key)


def resolve_superdocs(env=None, *, strict: bool = False) -> Endpoint:
    """The precedence rule, in the one place everything reads it from.

    1. `SUPERDOCS_API_KEY` set and non-empty -> that key, at
       `SUPERDOCS_BASE_URL` if given and the origin otherwise. A key its owner
       brought goes to the origin and nowhere else: handing it to relay would
       put somebody's own credential through infrastructure they did not
       choose, and relay refuses upstream-shaped keys anyway.
    2. else `RELAY_URL` and `RELAY_KEY` -> relay's SuperDocs mount. Both carry
       working defaults, which is what "it runs with no keys" actually means;
       setting either to empty is how a deployment opts out of relay entirely.
    3. else nothing is configured. `strict=True` raises naming both ways out.
       Otherwise an empty `Endpoint` comes back, because the styling pass has
       always been the optional half of this build: a missing key is a
       sentence somebody reads, not a crash.
    """
    env = os.environ if env is None else env

    own = (env.get("SUPERDOCS_API_KEY") or "").strip()
    if own:
        base = (env.get("SUPERDOCS_BASE_URL") or "").strip() or SUPERDOCS_ORIGIN
        return Endpoint(base.rstrip("/"), own, False)

    relay_url = (env.get("RELAY_URL", RELAY_URL) or "").strip()
    relay_key = (env.get("RELAY_KEY", RELAY_KEY) or "").strip()
    if relay_url and relay_key:
        return Endpoint(relay_url.rstrip("/") + RELAY_SUPERDOCS_PATH,
                        relay_key, True)

    if strict:
        raise NotConfigured(
            "Nothing to reach SuperDocs with. Set SUPERDOCS_API_KEY to your "
            "own key, or set RELAY_URL and RELAY_KEY to borrow one — "
            f"RELAY_URL={RELAY_URL} and RELAY_KEY={RELAY_KEY} work as they "
            "stand. See .env.example.")
    return Endpoint()


# -- retrying, and the four kinds of "too many" -------------------------------
#
# Retry the statuses that mean "later" and never the ones that mean "no": a
# 401 tried five times is five identical refusals and a slower answer to a
# question already settled.

RETRY_STATUSES = frozenset({429, 502, 503, 504})
NEVER_RETRY_STATUSES = frozenset({400, 401, 403, 404, 413, 422})
MAX_ATTEMPTS = 5
#: No single attempt ever sleeps longer than this, whatever `Retry-After`
#: asks for. The one `Retry-After` that would exceed it -- relay's, counting
#: to 00:00 UTC -- is not a wait at all but a stop, and never reaches a sleep.
RETRY_SLEEP_CAP = 60.0
BACKOFF_BASE = 1.0


class SuperDocsRefusal(RuntimeError):
    """A refusal specific enough to be worth telling somebody about, rather
    than a transport failure that only ever produces "it did not work"."""


class RationExhausted(SuperDocsRefusal):
    """Relay's daily ration is spent. Emphatically not a rate limit: its
    `Retry-After` counts to 00:00 UTC, so retrying is waiting out the day."""


class QuotaExhausted(SuperDocsRefusal):
    """SuperDocs' own monthly quota, arriving as an application 429 -- a JSON
    `detail` with a `Retry-After`. Surfaced, never spun on."""


class RequestTooLarge(SuperDocsRefusal):
    """Relay's request-body ceiling. Their own key has none."""


class ModelNotAllowed(SuperDocsRefusal):
    """Relay's model allowlist. Unreachable from this build, which names no
    model of its own -- kept so that if it ever does, the refusal says which
    models are allowed instead of arriving as "it did not work"."""


#: What a person reads when the shared ration is gone. One string, reused
#: everywhere it can happen, so the two paths that can hit it never drift into
#: telling somebody two different things. It names both ways out, because "try
#: again later" is the one piece of advice that does not work here: the ration
#: returns at midnight UTC and not before.
_RATION_NOTE = (
    "The shared styling allowance this copy of the page runs on is used up "
    "for today, so the file below is the plain rebuild — complete, and yours. "
    "It styles again tomorrow, or straight away if you put your own "
    "SUPERDOCS_API_KEY in .env."
)

#: When relay last said the daily ration was spent, and when it comes back.
#: Module-level because `web.py` builds a client per request, so anything
#: remembered on an instance is forgotten before it can be used. This is what
#: turns the ration into a *pre-flight* ceiling, read by `allowance()` in the
#: same breath as the monthly one, instead of something rediscovered by
#: spending a round trip on every attempt.
_RATION_SPENT_UNTIL = 0.0


def _note_ration_spent(retry_after: float | None) -> None:
    global _RATION_SPENT_UNTIL
    import time

    # Relay's own `Retry-After` counts to midnight UTC. Bounded at a day in
    # case it is missing or absurd: a ceiling that expires too early costs one
    # wasted request, one that never expires costs every request until the
    # process restarts.
    seconds = retry_after if retry_after and retry_after > 0 else 3600.0
    _RATION_SPENT_UNTIL = time.time() + min(seconds, 24 * 3600)


def _ration_is_spent() -> bool:
    import time

    return time.time() < _RATION_SPENT_UNTIL


def _header(resp, name: str):
    headers = getattr(resp, "headers", None) or {}
    try:
        return headers.get(name)
    except Exception:  # noqa: BLE001 -- a header map that will not be read
        return None


def _retry_after(resp) -> float | None:
    """`Retry-After` in seconds, uncapped. Uncapped on purpose: the sleep site
    caps it, and the ration needs the real number to know when the day ends."""
    raw = _header(resp, "Retry-After")
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        # The HTTP-date form. Nothing observed on this path emits it, and
        # guessing a date badly is worse than falling back to plain backoff.
        return None


def _body_of(resp):
    try:
        return resp.json()
    except Exception:  # noqa: BLE001 -- a plain-text body is a real answer
        return None


def _relay_code(body) -> str:
    """Relay's own refusals carry an `error` object; SuperDocs uses `detail`,
    so the presence of this is what tells the two apart. Branching on the code
    and never on the prose -- prose is somebody else's to reword."""
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    if not isinstance(err, dict):
        return ""
    return str(err.get("code") or "")


def _relay_message(body) -> str:
    if not isinstance(body, dict):
        return ""
    err = body.get("error")
    return str(err.get("message") or "") if isinstance(err, dict) else ""


def _backoff(attempt: int) -> float:
    """~1s, 2s, 4s, 8s, 16s with jitter. Jittered because every tab that hit
    the same limit in the same second would otherwise come back in the same
    second."""
    import random

    return BACKOFF_BASE * (2 ** (attempt - 1)) * (0.5 + random.random())


def _named_refusal(resp) -> None:
    """Raise when a non-retryable status is one relay explained, so the person
    gets the fix rather than "it did not work". Anything else returns quietly:
    every caller that reads a status itself -- `revert` reads 409 and 422 --
    must keep behaving exactly as it did."""
    body = _body_of(resp)
    code = _relay_code(body)
    if code in ("payload_too_large", "input_too_long"):
        mb = RELAY_MAX_REQUEST_BYTES // (1024 * 1024)
        raise RequestTooLarge(
            f"the shared allowance this page runs on caps a request at {mb} MB "
            "and this document is over it; a SUPERDOCS_API_KEY of your own has "
            "no such ceiling")
    if code == "forbidden_model":
        raise ModelNotAllowed(
            "the shared allowance this page runs on permits only "
            "deepseek/deepseek-v4-flash and "
            "google/gemini-embedding-2-preview@768")
    if code == "budget_exhausted":
        # Sent as a 429 in practice; carried on any other status it would mean
        # exactly the same thing, and spending attempts on a day that is
        # already over is the one thing this must not do.
        _note_ration_spent(_retry_after(resp))
        raise RationExhausted(_relay_message(body) or "the daily ration is spent")


def _wait_for_429(resp) -> float | None:
    """Seconds to wait before retrying a 429 -- or a raise, when the 429 means
    stop. Four kinds arrive on this path and only two are worth another
    attempt, so this branches on the body and never on the prose:

      * relay `budget_exhausted` -- the day's ration is gone. Stop. Its
        `Retry-After` counts to UTC midnight, so "retrying" would be sleeping
        through the reset with the connection held open.
      * relay `rate_limited`     -- relay's per-minute limiter. Retry.
      * SuperDocs `detail` with a `Retry-After` -- the application 429, i.e.
        the monthly quota. Surface it; spinning cannot earn quota back.
      * a plain-text body and no `Retry-After` -- infrastructure. Retry.
    """
    body = _body_of(resp)
    code = _relay_code(body)

    if code == "budget_exhausted":
        _note_ration_spent(_retry_after(resp))
        raise RationExhausted(_relay_message(body) or "the daily ration is spent")
    if code == "rate_limited":
        return _retry_after(resp)
    if (isinstance(body, dict) and body.get("detail") is not None
            and _header(resp, "Retry-After") is not None):
        raise QuotaExhausted(str(body.get("detail")))
    return _retry_after(resp)

#: The styling prompt, sent as `message` (the field the live SuperDocs chat
#: endpoint accepts). Carried verbatim from the spec.
INSTRUCTION = (
    "Formatting only. This document was recovered from a damaged file and its "
    "text is the only record of what its owner wrote. Normalize the formatting, "
    "restore heading styles, and keep every table and every image exactly as "
    "they are. Do NOT add, remove, expand, summarise, complete or reword any "
    "text. Do not add sections, headings, rows, totals, placeholders, "
    "disclaimers, signature blocks, headers, footers or dates. Do not fill "
    "gaps. If a passage looks incomplete, leave it exactly as it is. The "
    "word-for-word text of the output must be identical to the input. "
    "Target max 25 sections."
)

REQUEST_TIMEOUT = 300.0

#: The contract a conversational turn is wrapped in.
#:
#: This used to say "formatting only" and forbid adding, removing, expanding,
#: summarising, completing or rewording anything -- the same bounded contract
#: INSTRUCTION carries for the automatic pass. B20'' retired the refusal that
#: matched it (owner, 2026-08-26), and an envelope still arguing against what
#: the person just typed is worse than none: it makes the model hedge or
#: half-comply on an instruction the owner decided is theirs to give.
#:
#: What it bounds now is scope, not permission. Do what was asked; do not do
#: things that were not asked. That is the discipline worth keeping, because
#: a model handed a sparse recovered document will otherwise helpfully fill
#: it out -- observed on 2026-08-20, when a four-line report came back with
#: invented paragraphs, a subtotal row, a disclaimer and a signature block
#: that nobody had asked for.
TURN_ENVELOPE = (
    "This document was recovered from a damaged file, so its text is the "
    "only surviving record of what its owner wrote. Treat it as precious: "
    "never drop or replace content the request below does not ask you to "
    "touch. Do exactly what the request asks, and nothing beyond it -- add "
    "no sections, headings, rows, totals, placeholders, disclaimers, "
    "signature blocks, headers, footers or dates that were not asked for. "
    "If the request supplies exact words in quotes, use those words exactly "
    "as given.\n\nThe person's request: {message}"
)

#: Async job polling: a small backoff, capped, against a generous overall
#: budget -- async exists precisely so a turn that runs long survives past
#: the ~300s the synchronous endpoint 504s at (PRD §6), so the budget here is
#: wider than REQUEST_TIMEOUT rather than equal to it.
JOB_POLL_INITIAL = 2.0
JOB_POLL_MAX = 15.0
JOB_POLL_BUDGET = 900.0


def _bounded_turn(message: str) -> str:
    """Wrap a person's instruction in the same bounded contract INSTRUCTION
    carries, so it goes out evaluated inside a boundary rather than as free
    text the model could read as licence to write prose."""
    return TURN_ENVELOPE.format(message=message)


@dataclass
class Allowance:
    """The operations balance, and whether anybody actually read it.

    `period` is here because there are now two ceilings of the same kind and
    they reset on different clocks: SuperDocs meters a month, relay rations a
    day. It is a phrase rather than a flag so the one sentence a person reads
    ("no more changes can be made here …") stays true without every caller
    having to know which ceiling answered.
    """

    known: bool = False
    remaining: int = 0
    tier: str = ""
    period: str = "this month"


@dataclass
class Styling:
    """What the styling pass produced, and what to tell the person if nothing."""

    ok: bool = False
    output: bytes = b""
    #: One sentence, consumer-facing. Set on every path, success or not.
    note: str = ""
    stages: list = field(default_factory=list)
    #: Set when a styled file came back and was thrown away because its text or
    #: its pictures no longer matched. Kept apart from a transport failure: one
    #: is nobody's fault, the other is a claim we refused to pass on.
    rejected_for_content: bool = False
    ops_charged: int = 0
    allowance_known: bool = False
    allowance_remaining: int = 0
    #: The SuperDocs session this pass ran on. Minted the moment it exists,
    #: so a conversation can continue on the same document -- even on a
    #: later failure path, since the session itself may still be usable.
    session_id: str = ""


@dataclass
class Turn:
    """What one conversational instruction produced, and what to tell the
    person if nothing. Same discipline as `Styling`: every path, success or
    not, leaves `note` set to one consumer-facing sentence."""

    ok: bool = False
    output: bytes = b""              # the exported .docx after this turn
    note: str = ""                   # one consumer-facing sentence, set on EVERY path (B21)
    rejected_for_content: bool = False
    turn_index: int | None = None    # of the user message, for a later revert
    reconciled: bool = False         # True when recovered from a timeout rather than a clean reply
    stages: list = field(default_factory=list)
    # No operation count and no allowance here. The counter does not report
    # what it costs us: somebody whose file broke this morning did not arrive
    # with an account, and a number describing our metering is not something
    # they can act on. The allowance is still read before anything is sent
    # (B22) -- it decides whether to send, and says nothing further.


@dataclass
class Reverted:
    """What a native revert produced."""

    ok: bool = False
    note: str = ""
    compose_text: str = ""           # the instruction that was undone, to refill the field
    reverted_to_turn: int = -1
    archived_turn_count: int = 0


class SuperDocsClient:
    """A thin wrapper that performs upload -> instruct -> export."""

    def __init__(self, api_key: str | None = None,
                 base_url: str | None = None) -> None:
        """`api_key` and `base_url` override what the environment resolved to,
        in that order of specificity.

        The precedence rule itself lives in `resolve_superdocs` and is decided
        by the environment, which is where a deployment configures it. These
        two arguments are a seam for callers that already hold both halves --
        the tests, and anything that wants to point one client somewhere
        else -- so passing only `api_key` deliberately keeps the resolved base
        rather than silently re-deciding it. Nothing in this build passes
        either in production; `web.py` and `cli.py` construct it bare.
        """
        endpoint = resolve_superdocs()
        self.api_key = api_key or endpoint.api_key or None
        self.base = (base_url or endpoint.base_url).rstrip("/")
        self.using_relay = endpoint.using_relay and not base_url

    def style(self, sent: bytes, filename: str = "recovered.docx",
              on_progress=None) -> "Styling":
        """Upload, instruct, export. Never raises to its caller.

        Takes the rebuilt bytes rather than a path: the engine already holds
        them, and re-reading a file it just wrote is a second chance to read
        something else.

        Every failure returns `ok=False` with a sentence a non-engineer can act
        on. The caller still has the local rebuild, so a failure here degrades
        to "you get the plain file, and here is why" rather than to "you get
        nothing".
        """
        import uuid

        r = Styling()

        def say(msg: str) -> None:
            r.stages.append(msg)
            if on_progress:
                on_progress("Styling", msg)

        if not self.api_key:
            r.note = (
                "This copy of the page has no SuperDocs key set and no relay "
                "to borrow one from, so the file "
                "below is the plain rebuild. It is complete and it is yours; "
                "it just has not been through the styling pass."
            )
            log.info("Neither SUPERDOCS_API_KEY nor RELAY_URL/RELAY_KEY is "
                     "set; keeping the local rebuild.")
            return r

        try:
            # 0 -- the allowance, before a single billable call. Documented as
            # "useful before doing work (to confirm you have operations left)",
            # and reads are free. Starting a pass that cannot finish would leave
            # somebody watching a progress line for work refused at the far end.
            # Over relay this is also where the day's ration answers, which is
            # why the sentence says which clock ran out rather than assuming
            # the monthly one.
            left = self.allowance()
            r.allowance_known, r.allowance_remaining = left.known, left.remaining
            if left.known and left.remaining < 1:
                r.note = (
                    f"The SuperDocs styling allowance for {left.period} is used "
                    "up, so nothing was sent and nothing was spent. The file "
                    "below is the plain rebuild and it is still yours."
                )
                say(r.note)
                return r

            session_id = f"salvage-{uuid.uuid4().hex}"
            r.session_id = session_id

            say("Sending the recovered document to SuperDocs…")
            self._upload_bytes(sent, filename, session_id)

            # The docs warn that a first request in a fresh session can take
            # from thirty seconds to several minutes with no visible progress on
            # a large document. That is still processing, not a crash, and the
            # line above is what the person watching it needs to see.
            say("Restoring heading styles, tables and spacing…")
            self._instruct(session_id)

            say("Exporting the styled file…")
            got = self.export(session_id)
            if not got:
                r.note = ("SuperDocs returned no file, so the plain rebuild "
                          "below is what you get. Nothing was lost.")
                say(r.note)
                return r

            refusal = _why_not_acceptable(sent, got)
            if refusal:
                # Checked rather than trusted, because the styled file is the
                # one offered as better and so is the one that must not quietly
                # be worse. A recovered document handed back with the pictures
                # missing, or with sentences its owner never wrote, is a
                # downgrade wearing better formatting.
                r.rejected_for_content = True
                r.note = (
                    "The styled version came back " + refusal + ", so it was "
                    "thrown away rather than handed over. Your document should "
                    "say what you wrote. The plain rebuild below is unchanged "
                    "and still yours."
                )
                say(r.note)
                log.warning("SuperDocs styling rejected (%s)", refusal)
                return r

            r.output = got
            r.ok = True
            r.ops_charged = 1        # one document-modifying chat turn
            r.note = "SuperDocs returned a styled file."
            say("Styled file ready.")
            return r

        except RationExhausted:
            # Told apart from every other 429 on purpose: this one does not
            # come back with waiting, so offering "try again in a moment"
            # would be a suggestion that cannot work. The two things that do
            # work are named instead.
            r.note = _RATION_NOTE
        except QuotaExhausted:
            # SuperDocs' own monthly quota. Same shape of sentence, different
            # clock, and nothing to retry either.
            r.note = ("The SuperDocs styling allowance for this month is used "
                      "up, so the file below is the plain rebuild. It is "
                      "complete and it is yours.")
        except (RequestTooLarge, ModelNotAllowed) as exc:
            r.note = ("The styling pass could not run because " + str(exc) +
                      ". The file below is the plain rebuild and it is still "
                      "yours.")
        except requests.Timeout:
            r.note = ("SuperDocs did not answer in time. The plain rebuild "
                      "below is unchanged and still yours — you can try the "
                      "styling again on a fresh run.")
        except Exception as exc:  # noqa: BLE001 -- never escape the styling pass
            # Deliberately no exception class name: this string reaches a person.
            log.warning("SuperDocs styling failed (%s)", exc)
            r.note = ("The styling pass did not work this time, so the file "
                      "below is the plain rebuild. It is complete and it is "
                      "yours.")
        say(r.note)
        return r

    def styled_export(self, filepath: str) -> str:
        """Path-in, path-out wrapper kept for callers that hold a file.

        Returns the styled file's path on success, or `filepath` unchanged on
        any failure, exactly as before.
        """
        path = Path(filepath)
        r = self.style(path.read_bytes(), path.name)
        if not r.ok:
            return str(path)
        out = path.with_name("final_recovered.docx")
        out.write_bytes(r.output)
        return str(out)

    def allowance(self) -> "Allowance":
        """What the platform says is left, before anything is spent.

        `known` is false when the balance could not be read. That is not the
        same as zero and is never reported as one: an unreadable balance lets
        the work proceed and says the number is unknown, because refusing on a
        number nobody read would be its own kind of bluff.
        """
        # Relay's daily ration is the same kind of ceiling as the monthly
        # allowance -- a number that decides whether to send -- so it is
        # answered from here rather than bolted on beside it. It cannot be
        # read in advance: relay publishes no balance, so the only moment it
        # is knowable is the moment relay says no, which `_note_ration_spent`
        # remembers for the rest of the day. Until then this falls through to
        # the monthly read below, which over relay reports the shared
        # account's own quota -- a different ceiling, and a real one.
        if self.using_relay and _ration_is_spent():
            return Allowance(known=True, remaining=0, tier="relay",
                             period="today")
        try:
            resp = self._request("GET", "/v1/agents/whoami", timeout=30)
            resp.raise_for_status()
            quota = (resp.json() or {}).get("quota") or {}
            if "remaining" not in quota:
                return Allowance()
            return Allowance(known=True, remaining=int(quota["remaining"]),
                             tier=str(quota.get("tier", "")))
        except Exception:  # noqa: BLE001 -- an unread balance is not a zero one
            return Allowance()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(self, method: str, path: str, *, retry_5xx: bool = True,
                 **kwargs):
        """Every HTTP call this module makes, retried where retrying helps.

        One funnel, for two reasons. The base and the key differ between the
        origin and relay and are decided once here rather than at eleven call
        sites. And a 429 has to be *read* rather than assumed: relay's daily
        ration and relay's per-minute limiter arrive with the same status
        code, and treating the first like the second means five attempts, a
        held connection, and the same answer at the end of it.

        The response comes back unraised: callers that read a status
        themselves (`revert` reads 409 and 422) and callers that call
        `raise_for_status` both keep working exactly as they did.

        `retry_5xx=False` is how a *billable* write opts out of the timeout
        and 5xx half of the policy. B30 and PRD §6: there is no idempotency
        key on a SuperDocs write, so a 504 on `/v1/chat` may mean the edit
        landed and the answer was lost, and repeating it would charge twice
        for a document edited twice. Those calls are reconciled instead of
        resent. The 429 half still applies to them, because every 429 on this
        path -- relay's limiter, relay's ration, SuperDocs' quota -- is a
        refusal taken before any work was done and so before anything was
        charged.
        """
        import time

        # Resolved from the module at call time, not bound at import: the
        # suite patches `superdocs_client.requests` and must keep being able
        # to.
        send = requests.post if method == "POST" else requests.get
        url = f"{self.base}{path}"
        headers = {**self._headers(), **(kwargs.pop("headers", None) or {})}

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = send(url, headers=headers, **kwargs)
            except requests.Timeout:
                # A timeout is the one transport failure worth repeating: the
                # request may well have been received. A refused connection or
                # an unresolvable host is a definitive no, and is left to
                # raise on the first attempt rather than costing four more.
                if attempt == MAX_ATTEMPTS or not retry_5xx:
                    raise
                time.sleep(min(_backoff(attempt), RETRY_SLEEP_CAP))
                continue

            status = getattr(resp, "status_code", 200)
            if status == 429:
                wait = _wait_for_429(resp)       # raises when it means stop
            elif status in RETRY_STATUSES and retry_5xx:
                wait = _retry_after(resp)
            else:
                if status in NEVER_RETRY_STATUSES:
                    _named_refusal(resp)
                return resp

            if attempt == MAX_ATTEMPTS:
                # Out of attempts: hand back the refusal itself so the
                # caller's own `raise_for_status` says so, rather than
                # inventing an exception the caller does not expect.
                return resp
            time.sleep(min(wait if wait is not None else _backoff(attempt),
                           RETRY_SLEEP_CAP))
        return resp

    def _upload_bytes(self, blob: bytes, filename: str, session_id: str) -> None:
        """Load the rebuilt document as the session's active editable document.

        Sent as a file, which is the documented contract: SuperDocs takes
        documents and HTML, and there is no endpoint for raw Word XML. Uploading
        the `.docx` is also what carries the pictures — the upload path extracts
        images to cloud storage and the export preserves them, so they survive
        without a separate image call.
        """
        # The bytes go in directly rather than wrapped in a `BytesIO`: a
        # stream is consumed by the first attempt, so a retry would upload an
        # empty file and the session would style nothing at all.
        resp = self._request(
            "POST", "/v1/documents/upload",
            files={"file": (filename, blob)},
            data={"session_id": session_id},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()

    def _upload(self, filepath: str, session_id: str) -> None:
        # Loads the local rebuild as the session's active, editable document.
        # Synchronous: the response returns the parsed HTML and the session_id.
        # Read whole rather than streamed from the handle, for the same reason
        # `_upload_bytes` does not wrap its blob: a retry re-sends the body,
        # and a handle already at EOF would send nothing.
        path = Path(filepath)
        self._upload_bytes(path.read_bytes(), path.name, session_id)

    def _instruct(self, session_id: str) -> None:
        # Synchronous chat: the AI normalizes/restyles the session's document and
        # applies the change immediately (auto-approve). No approval step required.
        # Billable, so no 5xx retry: see `_request`. A 429 is still retried,
        # because relay and SuperDocs alike refuse before charging.
        self._request(
            "POST", "/v1/chat", retry_5xx=False,
            json={"message": INSTRUCTION, "session_id": session_id},
            timeout=REQUEST_TIMEOUT,
        ).raise_for_status()

    def export(self, session_id: str) -> bytes | None:
        """The session's current document, as `.docx` bytes. Free (PRD §7)."""
        resp = self._request(
            "POST", "/v1/documents/export",
            json={"session_id": session_id, "format": "docx"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content or None

    def _export(self, session_id: str) -> bytes | None:
        # Kept as a thin alias: `export` is the public name now, but this
        # name stayed in case anything outside this file still reaches for
        # it directly.
        return self.export(session_id)

    # -- the conversation ------------------------------------------------

    def open_session(self, rebuild: bytes, filename: str = "recovered.docx") -> str:
        """Mint a session and load the rebuild into it as the active
        document, so a conversation can continue turn after turn on the
        same file.

        Never raises: a caller only ever gets back an id it can hold a
        conversation on. If the upload itself does not take, the first turn
        sent on this session will not find its edit landing, and
        reconciliation there is what surfaces it -- retrying the upload
        blindly here would carry the same double-billing risk `turn` is
        built to avoid, except spent on an upload rather than an edit.
        """
        import uuid

        session_id = f"salvage-{uuid.uuid4().hex}"
        try:
            self._upload_bytes(rebuild, filename, session_id)
        except Exception as exc:  # noqa: BLE001 -- never raise on session open
            log.warning("SuperDocs session open failed to upload (%s)", exc)
        return session_id

    def turn(self, session_id: str, message: str, *, sent: bytes,
             authorised, on_progress=None) -> "Turn":
        """One conversational instruction, applied and verified.

        Goes over the asynchronous chat endpoint (PRD §6): synchronous
        `/v1/chat` 504s past about 300 seconds, and there is no idempotency
        key on a billable write, so a turn that cannot be confirmed is
        reconciled against the session's own document version rather than
        ever resent. `approval_mode` is never set -- edits auto-apply, and
        the job must never reach `awaiting_approval`.

        `sent` is the version this turn started from (for the picture
        count) and `authorised` is the authorised word baseline (PRD §3) the
        guard checks the result against. Never raises -- every path returns
        a populated `Turn` with a note a non-engineer can act on.
        """
        r = Turn()

        def say(msg: str) -> None:
            r.stages.append(msg)
            if on_progress:
                on_progress("Styling", msg)

        # The free "did my edit land?" signal for reconciliation is the
        # session's document version id (`_version_id`, via the free
        # history read) -- it moves exactly when an edit lands and needs no
        # id resolution. `structure` is the documented "did my edit land"
        # read too, but it needs a durable document id resolved first
        # (`_durable_document_id`), so it stays a correct public helper
        # rather than the thing on this hot path.
        before_version = self._version_id(session_id)

        try:
            say("Sending your change to SuperDocs…")
            # Billable, so no 5xx retry (B30): a turn that cannot be confirmed
            # is reconciled below, never resent.
            resp = self._request(
                "POST", "/v1/chat/async", retry_5xx=False,
                json={"session_id": session_id, "message": _bounded_turn(message),
                      "response_mode": "compact"},
                timeout=30,
            )
            resp.raise_for_status()
            job_id = (resp.json() or {}).get("job_id")
            if not job_id:
                raise ValueError("no job id in the response")

            say("Applying your change…")
            body = self._await_job(job_id, say)
            status = (body or {}).get("status")

            if status == "completed":
                result = (body or {}).get("result") or {}
                turn_index = ((body or {}).get("metadata") or {}).get(
                    "user_turn_index_pre_inserted")
                self._finish_turn(r, session_id, sent, authorised, say,
                                  turn_index=turn_index,
                                  document_changes=result.get("document_changes"))
                return r

            # A definitive no from the platform -- failed or cancelled -- is
            # not ambiguous, so there is nothing to reconcile: the edit did
            # not land.
            r.note = ("SuperDocs could not apply that change, so your "
                      "document is unchanged. You can try again.")
            say(r.note)
            return r

        except SuperDocsRefusal as exc:
            # Not ambiguous and so not reconciled: a refusal means the turn
            # was turned away before any work happened, and telling somebody
            # "it may have landed, check back" about a request that was never
            # accepted is the opposite of what they need to hear.
            log.warning("SuperDocs turn refused (%s)", exc)
            if isinstance(exc, (RationExhausted, QuotaExhausted)):
                # The counter's own sentence for a ceiling, not the styling
                # pass's: there is no "file below" here, and what the person
                # needs is the same one line the pre-flight would have given
                # them had the number been readable a moment earlier. Which
                # clock ran out is the only difference.
                from . import counter as _counter

                r.note = _counter.no_allowance_left(
                    "today" if isinstance(exc, RationExhausted) else "this month")
            else:
                # `RequestTooLarge` and `ModelNotAllowed` carry their own fix
                # in the message, which is the whole reason they are separate
                # from a bare transport failure.
                r.note = ("That change could not be sent because " + str(exc) +
                          ". Your document is unchanged.")
            say(r.note)
            return r

        except Exception as exc:  # noqa: BLE001 -- never raise out of a turn
            # Timeout, 5xx, an unreadable job: never resend. Reconcile
            # against the session's own document version instead.
            log.warning("SuperDocs turn could not be confirmed (%s)", exc)
            self._reconcile_turn(r, session_id, before_version, sent,
                                 authorised, say)
            return r

    def _await_job(self, job_id: str, say) -> dict | None:
        """Poll a chat job to a terminal state, with a small backoff. Emits a
        progress line while it runs (B5: stages are real, not simulated).
        Raises on a poll failure or a budget overrun -- caught by `turn`,
        which reconciles rather than resending."""
        import time

        delay = JOB_POLL_INITIAL
        deadline = time.monotonic() + JOB_POLL_BUDGET
        while True:
            resp = self._request("GET", f"/v1/jobs/{job_id}", timeout=30)
            resp.raise_for_status()
            body = resp.json() or {}
            status = body.get("status")
            if status in ("completed", "failed", "cancelled"):
                return body
            if status == "awaiting_approval":
                # Should never happen -- approval_mode is never set on this
                # path. Treated as unreadable rather than trusted, and the
                # job is asked to stop rather than left running unattended.
                try:
                    self._request("POST", f"/v1/jobs/{job_id}/cancel",
                                  timeout=30)
                except Exception:  # noqa: BLE001
                    pass
                raise TimeoutError("job asked for approval unexpectedly")
            if time.monotonic() >= deadline:
                raise TimeoutError("job poll exceeded its budget")
            progress = body.get("progress")
            say("Still applying your change…" +
                (f" {progress}%" if isinstance(progress, int) else ""))
            time.sleep(delay)
            delay = min(delay * 2, JOB_POLL_MAX)

    def _reconcile_turn(self, r: "Turn", session_id: str, before_version,
                        sent: bytes, authorised, say) -> None:
        """PRD §6: never blind-retry. Compare the session's document version
        id -- free, via `history` -- and only treat the edit as landed when
        it demonstrably moved. An unreadable id, before or after, is not
        evidence either way, so it is never read as "unchanged"."""
        after_version = self._version_id(session_id)
        if before_version is None or after_version is None:
            r.note = ("That change did not come back in time, and "
                      "SuperDocs cannot be reached to check whether it "
                      "landed. Nothing has been sent again; check back "
                      "before trying once more.")
            say(r.note)
            return
        if after_version == before_version:
            r.note = ("That change did not come back in time, and "
                      "checking your document shows nothing changed. You "
                      "can send it again.")
            say(r.note)
            return
        r.reconciled = True
        self._finish_turn(r, session_id, sent, authorised, say,
                          reconciled=True)

    def _finish_turn(self, r: "Turn", session_id: str, sent: bytes, authorised,
                     say, *, reconciled: bool = False,
                     turn_index: int | None = None,
                     document_changes=None) -> None:
        """Export, guard, and populate a landed edit's `Turn` -- shared by
        the clean-completion path and the reconcile path, since both end the
        same way once the edit is known to have landed."""
        from . import counter as _counter

        say("Exporting the changed file…")
        got = self.export(session_id)
        if not got:
            r.note = ("SuperDocs changed your document but did not send the "
                      "file back, so what you can download here is unchanged.")
            say(r.note)
            return

        # Nothing is refused here for changing the wording. At the counter
        # the person asked for it, and the owner's decision on 2026-08-26 is
        # that what they ask for is theirs to ask (B20''). The automatic pass
        # is unchanged and still refuses -- that is where the model acts with
        # nobody watching.
        #
        # It is still said. A turn that quietly removed seventy-three words
        # would be the silence this build has never allowed, whatever the
        # refusal rules are.
        changed = _counter.describe_change(sent, got, authorised)

        r.ok = True
        r.output = got
        # The job hands back the user message's own turn index; only the
        # reconcile path -- which never sees a job body -- falls back to
        # reading it from history.
        r.turn_index = (int(turn_index) if turn_index is not None
                        else self._last_turn_index(session_id))
        r.note = self._turn_receipt(document_changes, changed,
                                    reconciled=reconciled)
        say(r.note)

    def _turn_receipt(self, document_changes, changed: str, *,
                      reconciled: bool) -> str:
        """One consumer-facing sentence for a landed edit.

        Uses the compact per-section diff when SuperDocs sent one, so the
        receipt names that something specific changed rather than only that
        the turn landed -- and adds what it did to the words when that is
        not nothing. A person who asks for a formatting change and gets
        seventy-three words fewer should be told in the same breath as being
        told it worked.
        """
        prefix = ("That change took longer than expected, but it landed."
                 if reconciled else "SuperDocs applied your change.")
        if isinstance(document_changes, list) and document_changes:
            count = len(document_changes)
            noun = "section" if count == 1 else "sections"
            prefix = f"{prefix} {count} {noun} changed."
        if changed:
            prefix = f"{prefix} Also {changed}."
        return prefix

    def _history_body(self, session_id: str) -> dict | None:
        """Raw read of `GET /v1/sessions/{id}/history` --
        `{document_state, editor_action, messages, restore_error,
        session_id}`. Free. `None` when it could not be read."""
        try:
            resp = self._request(
                "GET", f"/v1/sessions/{session_id}/history", timeout=30)
            resp.raise_for_status()
            return resp.json() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("SuperDocs history read failed (%s)", exc)
            return None

    def _version_id(self, session_id: str) -> str | None:
        """The session's current document version id
        (`document_state.version_id`), which moves exactly when an edit
        lands. `None` when the history read failed -- not the same as
        "unchanged", and callers must not treat it as one."""
        body = self._history_body(session_id)
        if body is None:
            return None
        return (body.get("document_state") or {}).get("version_id")

    def document_html(self, session_id: str) -> str:
        """SuperDocs' own rendering of the session's document, with the
        formatting still on it.

        This is what the page shows after a turn, and it has to be, because
        the alternative does not work: rebuilding the preview from the
        exported `.docx` goes through `docx.blocks_to_html`, which carries
        structure and text and no formatting at all. Ask for smaller headings
        and that preview comes back byte-identical -- the change is real, in
        the file, and invisible on the screen. A page that cannot show the
        change it just made is worse than one that never offered to.

        Free (a history read). Empty string when it could not be read, which
        costs the preview and never the turn.
        """
        body = self._history_body(session_id)
        if body is None:
            return ""
        return (body.get("document_state") or {}).get("html_content") or ""

    def _last_turn_index(self, session_id: str) -> int | None:
        body = self._history_body(session_id)
        entries = (body or {}).get("messages") or []
        if not entries:
            return None
        idx = entries[-1].get("turn_index")
        return int(idx) if idx is not None else None

    def revert(self, session_id: str, turn_index: int) -> "Reverted":
        """Undo the given user turn and its edit together -- native revert,
        not a re-upload, because SuperDocs restores the conversation and the
        document as one unit (PRD §8). Free; the turn cap is the only limit
        on how often this can be pressed. Never raises.
        """
        r = Reverted()
        try:
            resp = self._request(
                "POST", f"/v1/sessions/{session_id}/revert",
                json={"turn_index": turn_index},
                timeout=30,
            )
            if resp.status_code == 409:
                r.note = ("That change is still going through. You can put "
                          "it back once it has landed.")
                return r
            if resp.status_code == 422:
                r.note = ("That change is too old for SuperDocs to undo on "
                          "its own, so nothing was changed here.")
                return r
            resp.raise_for_status()
            body = resp.json() or {}
            r.ok = True
            r.compose_text = str(body.get("compose_text", "") or "")
            r.reverted_to_turn = int(body.get("reverted_to_turn", -1))
            r.archived_turn_count = int(body.get("archived_turn_count", 0) or 0)
            r.note = "That change has been put back."
            return r
        except Exception as exc:  # noqa: BLE001 -- never raise out of a revert
            log.warning("SuperDocs revert failed (%s)", exc)
            r.note = ("That change could not be put back just now. Your "
                      "document is unchanged.")
            return r

    def history(self, session_id: str) -> list[dict]:
        """The session's message history, each entry carrying `turn_index`
        and `checkpoint_id` (PRD §8). Free. Never raises -- an unreadable
        history comes back empty rather than failing its caller."""
        body = self._history_body(session_id)
        if body is None:
            return []
        entries = body.get("messages")
        if entries is None:
            entries = body.get("history") or []
        return list(entries)

    def _durable_document_id(self, session_id: str) -> str | None:
        """Resolve the session's focused document to the permanent id
        `structure` needs. `GET /v1/documents/{id}` 400s on the session id
        and on the session-local slot id (e.g. `doc_primary`) alike -- it
        wants `durable_document_id`, which only this free read
        (`GET /v1/sessions/{id}/documents`) carries."""
        try:
            resp = self._request(
                "GET", f"/v1/sessions/{session_id}/documents", timeout=30)
            resp.raise_for_status()
            body = resp.json() or {}
            docs = body.get("documents") or []
            focused = body.get("focused_document_id")
            for doc in docs:
                if doc.get("document_id") == focused:
                    return doc.get("durable_document_id")
            if docs:
                return docs[0].get("durable_document_id")
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("SuperDocs durable document id lookup failed (%s)", exc)
            return None

    def structure(self, session_id: str) -> dict | None:
        """The document's structure -- section_count, block_count, media --
        documented as the free "did my edit land?" read (PRD §6). Correct
        and kept public, but turn-level reconciliation uses the session's
        document version instead (`_version_id`), which needs no id
        resolution; this one does, via `_durable_document_id`, so it costs
        an extra free round trip. `None` when either read fails, which is
        not the same as "unchanged" and callers must not treat it as one."""
        try:
            durable_id = self._durable_document_id(session_id)
            if not durable_id:
                return None
            resp = self._request(
                "GET", f"/v1/documents/{durable_id}", timeout=30)
            resp.raise_for_status()
            body = resp.json() or {}
            return body.get("structure", body)
        except Exception as exc:  # noqa: BLE001
            log.warning("SuperDocs structure read failed (%s)", exc)
            return None


def _picture_count(blob: bytes) -> int:
    """How many readable pictures a `.docx` actually carries."""
    import io
    import zipfile

    from . import media

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            total = 0
            for n in z.namelist():
                if not n.startswith(media.MEDIA_DIR):
                    continue
                blob = z.read(n)
                if media.sniff_ext(blob) and media.is_complete(blob):
                    total += 1
            return total
    except Exception:  # noqa: BLE001 -- an unreadable answer is not a count
        return 0


def _words(text: str) -> list[str]:
    """Text reduced to what a reader would call the words, so that a formatting
    pass -- which may re-wrap, re-space or re-escape -- reads as no change."""
    import html as _html
    import re

    plain = _html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.findall(r"[a-z0-9]+", plain.lower())


def docx_text(blob: bytes) -> str:
    """The text of a `.docx`, run by run. Deliberately not a full parse: this is
    asked only "what does it say"."""
    import io
    import re
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            body = z.read("word/document.xml").decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", body))


def content_drift(sent: bytes, got: bytes) -> tuple[int, int]:
    """(words added, words removed) between what we sent and what came back.

    A multiset rather than a sequence: reordering a table's cells is not this
    guard's business, and inventing a paragraph is.
    """
    from collections import Counter

    before = Counter(_words(docx_text(sent)))
    after = Counter(_words(docx_text(got)))
    return sum((after - before).values()), sum((before - after).values())


def _why_not_acceptable(sent: bytes, got: bytes) -> str:
    """Empty when the styled file may be handed over, else the reason it may not.

    Two checks, both on the same principle: a formatting pass has no business
    changing what the document *is*.

    * **Pictures.** The styling path used to send HTML with the images stripped
      out of it, so every styled file came back with no pictures at all and
      nothing noticed. It now sends the rebuilt file, whose pictures travel with
      it -- and counts them on the way back, because "the docs say images are
      preserved" is a reason to expect it, not a reason to skip checking.
    * **Words.** A document-editing model handed a sparse recovered file will
      fill it out -- observed live on 2026-08-20, where a four-line report came
      back with invented paragraphs, a subtotal row, a disclaimer and a
      signature block. Handing that to somebody who came here to get their own
      words back is the worst output this product could produce: it opens
      cleanly, it looks better than the plain rebuild, and it is partly fiction.
    """
    before, after = _picture_count(sent), _picture_count(got)
    if after < before:
        return f"with {before - after} fewer pictures than it was sent"

    added, removed = content_drift(sent, got)
    if added + removed:
        return f"with the wording changed ({added} added, {removed} removed)"
    return ""
