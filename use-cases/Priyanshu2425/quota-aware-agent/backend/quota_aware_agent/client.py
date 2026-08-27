"""The four-call contract: upload, edit instruction, approve, export.

Everything here is grounded in the SuperDocs documentation, and the three traps
the docs name by hand are handled explicitly rather than discovered later:

  Trap 1 -- the double parse. A `proposed_change_batch` envelope carries its
    payload as a JSON-encoded *string* in `content`. `parse_proposed_changes`
    does the second parse. Skipping it is the documented single most common
    reason integrators see empty diff cards with every field undefined.

  Trap 2 -- silence is not a crash. A job on a large document can run for
    minutes with no visible progress. `poll_job` treats a long quiet run as
    still processing and only gives up at an explicit deadline, reporting how
    long it waited rather than calling it a failure.

  Trap 3 -- the allowance. Every response carries a `usage` block; nothing here
    spends without handing that block back to the caller to reconcile.

Transport is injected. `HttpTransport` is the real one; the tests pass a fake,
which is why this file has no network dependency and the suite needs no key.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

BASE = "https://api.superdocs.app"

#: The relay mounts SuperDocs under this prefix and leaves every path below it
#: unchanged, so it is a base-URL swap and nothing else -- which is why nothing
#: in this file below `resolve` knows which of the two it is talking to.
RELAY_SUPERDOCS_PATH = "/v1/superdocs"

#: SuperDocs operations the relay lends per key per day, resetting at 00:00 UTC.
#: A *second* ceiling sitting under the account's monthly allowance; `budget.py`
#: models it, because this file must not be the place that decides what fits.
RELAY_DAILY_OPS = 460

#: Sent on every request. Not politeness: the relay sits behind Cloudflare,
#: which answers the stdlib default `Python-urllib/3.x` with `403 error code:
#: 1010` -- a bot-management block whose body is plain text and mentions
#: neither a key nor a quota, so it reads like a permissions problem and is not
#: one. Verified against the live relay 2026-08-27: `Python-urllib/3.13` is
#: refused, and `curl`, `python-requests`, `httpx`, a named agent -- even NO
#: user agent at all -- are all answered 200. Only the urllib default is
#: blocked, which is precisely the one a dependency-free build sends.
#:
#: DO NOT REMOVE THIS AS TIDYING. It looks like a decorative header and it is
#: the difference between the relay path working and answering 403 with a body
#: that says nothing about user agents. The same trap is known elsewhere in
#: this codebase (Attest carries `ATTEST_JWKS_USER_AGENT` because Cloudflare
#: refuses PyJWT's urllib client for the same reason), so it is a hazard of the
#: stdlib client rather than a quirk of this relay.
USER_AGENT = "quota-aware-agent/1.0 (+https://github.com/Priyanshu2425)"

# Terminal and non-terminal job states, from the docs' job lifecycle.
_TERMINAL = {"completed", "failed", "cancelled"}
_NEEDS_HUMAN = "awaiting_approval"


class Transport(Protocol):
    def request(self, method: str, path: str, **kw: Any) -> "Response": ...


@dataclass
class Response:
    status: int
    body: dict
    headers: dict = field(default_factory=dict)

    @property
    def usage(self) -> dict:
        """The usage block rides on every chat response. It is the only way to
        read the balance from an API-key context -- the account usage endpoints
        reject `sk_` keys with a 401."""
        return self.body.get("usage", {}) or {}


@dataclass(frozen=True)
class Endpoint:
    """Where SuperDocs is, which key opens it, and what that costs you.

    `daily_ration` is None on the direct path on purpose rather than being some
    large number: "there is no second ceiling" and "the second ceiling is high"
    are different facts, and only the first one can be stated honestly here.
    """

    base: str
    key: str
    using_relay: bool
    daily_ration: int | None = None


#: Named once so the two callers that can hit it -- the MCP server and the CLI
#: -- cannot describe the same situation differently. Both remedies are named,
#: because they are not equivalent and the reader has to be able to choose.
NO_CREDENTIALS = (
    "No SuperDocs credentials are set. Two ways to fix that, and they are not "
    "the same thing:\n"
    "  * RELAY_URL and RELAY_KEY -- the shared relay. No signup at all: it holds "
    "the key and lends it under a ration of "
    f"{RELAY_DAILY_OPS} SuperDocs operations per key per day, resetting at "
    "00:00 UTC. `cp .env.example .env` sets both, and the relay key is not a "
    "secret.\n"
    "  * SUPERDOCS_API_KEY -- your own key. The build then calls "
    f"{BASE} directly: no ration, and the key never reaches infrastructure "
    "somebody else operates and logs. An agent account can be created with "
    "POST /v1/agents/signup."
)


def resolve(env: Mapping[str, str] | None = None) -> Endpoint:
    """Where to send SuperDocs calls, and with what key.

    Own key wins. That is a security position and not a convenience: a key of
    yours goes straight to the origin and is never handed to the relay, which
    would otherwise see and log it. The relay refuses `sk_`-shaped keys with a
    401 anyway, but being refused is not the same as not trying.
    """
    env = os.environ if env is None else env
    own = (env.get("SUPERDOCS_API_KEY") or "").strip()
    if own:
        base = (env.get("SUPERDOCS_BASE_URL") or BASE).strip().rstrip("/")
        return Endpoint(base=base, key=own, using_relay=False)

    relay_url = (env.get("RELAY_URL") or "").strip().rstrip("/")
    relay_key = (env.get("RELAY_KEY") or "").strip()
    if relay_url and relay_key:
        return Endpoint(base=relay_url + RELAY_SUPERDOCS_PATH, key=relay_key,
                        using_relay=True, daily_ration=RELAY_DAILY_OPS)

    raise RuntimeError(NO_CREDENTIALS)


class SuperDocsError(RuntimeError):
    def __init__(self, status: int, body: Any, remedy: str = "") -> None:
        super().__init__(self._message(status, body, remedy))
        self.status = status
        self.body = body
        #: What the reader should do about it, when there is a specific answer.
        self.remedy = remedy

    @staticmethod
    def _message(status: int, body: Any, remedy: str) -> str:
        return f"SuperDocs returned {status}: {body}" + (f" -- {remedy}" if remedy else "")


class QuotaExhausted(SuperDocsError):
    """Raised only when the platform says so. Never inferred from our own count."""


class RelayRefused(SuperDocsError):
    """The relay itself refused, before SuperDocs ever saw the request.

    Told apart from an upstream error by the shape of the body: the relay
    answers with an `error` object, SuperDocs with `detail`. Branching on that
    rather than on the prose is the difference between a rule and a guess.

    Nothing here is retryable, so every one of these carries the fix in words.
    """

    @staticmethod
    def _message(status: int, body: Any, remedy: str) -> str:
        code = relay_error(body).get("code") or status
        return f"the relay refused this request ({code}). {remedy}"


class RationExhausted(RelayRefused):
    """The relay's daily ration is spent. Not a rate limit -- a ceiling.

    Deliberately NOT retried: `Retry-After` on this one counts down to 00:00
    UTC, so a client honouring it would sleep for hours and a client ignoring it
    would spin. Both are worse than saying so.
    """

    def __init__(self, status: int, body: Any, remedy: str = "",
                 retry_after_s: float | None = None) -> None:
        super().__init__(status, body, remedy)
        #: Seconds to the reset, as the relay stated it. Reported, never slept.
        self.retry_after_s = retry_after_s


class TransportFailure(RuntimeError):
    """The call did not produce a response, and we have to say which kind.

    The distinction is the whole point. A connection that was refused means the
    request never reached SuperDocs and cannot have been billed, so a rerun may
    safely repeat it. A read that timed out means the request very possibly did
    reach SuperDocs, was charged, and applied an edit -- we simply never heard
    the answer. Collapsing the two into "it failed" is how a retry pays twice.
    """

    def __init__(self, message: str, *, never_sent: bool) -> None:
        super().__init__(message)
        self.never_sent = never_sent


def provably_never_sent(exc: BaseException) -> bool:
    """True only when the request cannot have been billed.

    Deliberately conservative: the default answer is "we do not know", because
    the cost of wrongly believing a call was billed is one step reported to a
    person, and the cost of wrongly believing it was not is the user paying
    twice and possibly getting the same edit applied twice.
    """
    import socket

    if isinstance(exc, TransportFailure):
        return exc.never_sent
    if isinstance(exc, QuotaExhausted):
        # The request that carried this signal completed; it was answered.
        return False
    if isinstance(exc, SuperDocsError):
        # A 4xx was rejected before any work happened, so it was not billed.
        # A 5xx may have come from a gateway that had already passed the
        # request on, so it proves nothing.
        return exc.status < 500
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (ConnectionRefusedError, socket.gaierror))


# -- retrying, and the four different 429s that must not be treated alike ----

#: Worth trying again. Everything else -- 400, 401, 403, 404, 413, 422 -- is a
#: refusal that will be refused again, and retrying it only delays the message.
_RETRYABLE_STATUS = {429, 502, 503, 504}

#: Never sleep longer than this in one attempt, however long a `Retry-After`
#: says. A client that sleeps for hours is indistinguishable from one that hung.
_MAX_SLEEP_S = 60.0


def relay_error(body: Any) -> dict:
    """The relay's error envelope, or `{}` if this did not come from the relay.

    The whole classification below hangs off this one shape test: the relay
    answers `{"error": {"code": ...}}`, SuperDocs answers `{"detail": ...}`, and
    an infrastructure 429 answers plain text. Matching on prose would break the
    first time somebody reworded a message.
    """
    if not isinstance(body, dict):
        return {}
    err = body.get("error")
    return err if isinstance(err, dict) else {}


def retry_after_seconds(headers: Mapping[str, Any] | None,
                        cap: float | None = _MAX_SLEEP_S) -> float | None:
    """`Retry-After`, in seconds, honouring both documented forms."""
    raw = ""
    for name, value in (headers or {}).items():
        if str(name).lower() == "retry-after":
            raw = str(value).strip()
            break
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone

            when = parsedate_to_datetime(raw)
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            seconds = (when - datetime.now(timezone.utc)).total_seconds()
        except Exception:
            return None
    seconds = max(0.0, seconds)
    return seconds if cap is None else min(cap, seconds)


def relay_charges_for(path: str) -> bool:
    """Does the relay bill a SuperDocs operation for this path?

    Its rule is `/v1/chat`, `/v1/chat/async` and re-edits -- uploads, exports,
    job polls, session reads and whoami are free. `/v1/chat/{id}/approve` is how
    a re-edit is asked for, and it sits under the same prefix, so one prefix
    test covers all three. This is also, and not by coincidence, the set of
    calls that can be *billed*, which is why the retry rules consult it.
    """
    return path.startswith("/v1/chat")


def stop_signal(status: int, body: Any, headers: Mapping[str, Any] | None) -> None:
    """Raise on the relay refusals that no amount of waiting will fix.

    Called on every response, before any retry decision, because retrying any
    of these is not slower -- it is wrong.
    """
    code = str(relay_error(body).get("code") or "")
    if not code:
        return
    if code == "budget_exhausted":
        wait = retry_after_seconds(headers, cap=None)
        when = (f" It resets in about {wait / 3600:.1f}h (00:00 UTC)."
                if wait else " It resets at 00:00 UTC.")
        raise RationExhausted(
            status, body,
            f"The shared relay lends {RELAY_DAILY_OPS} SuperDocs operations per "
            f"key per day and today's are spent, so this was refused and NOT "
            f"billed.{when} Set SUPERDOCS_API_KEY to your own key to bypass the "
            "ration entirely, or wait. Retrying will not help.",
            retry_after_s=wait,
        )
    if code == "forbidden_model":
        raise RelayRefused(
            status, body,
            "The relay allows only 'deepseek/deepseek-v4-flash' for chat and "
            "'google/gemini-embedding-2-preview@768' for embeddings. This build "
            "sends no model field at all, so seeing this means something else "
            "is putting one on the request. Set SUPERDOCS_API_KEY to lift the "
            "allowlist.")
    if code in ("input_too_long", "payload_too_large"):
        ceiling = ("24,000 input tokens (estimated at 4 chars/token)"
                   if code == "input_too_long" else "an 8 MB request body")
        raise RelayRefused(
            status, body,
            f"The relay caps a request at {ceiling}, and this one is over it. "
            "Split the document or the instruction, or set SUPERDOCS_API_KEY to "
            "call SuperDocs directly, where only its own ~20 MB upload ceiling "
            "applies. Nothing was billed.")


def retry_wait(response: "Response", *, method: str, path: str,
               attempt: int) -> float | None:
    """Seconds to wait before repeating this request, or None to hand the
    response back to the caller as it stands.

    Two rules are doing the work here, and only the first one comes from the
    relay contract.

    **Which 429 is it.** Four of them arrive at this line and three want
    different answers:

      * `error.code == "rate_limited"` -- the relay's per-minute limiter. Wait
        and repeat; the window is 60 seconds wide.
      * `error.code == "budget_exhausted"` -- already raised by `stop_signal`
        above and never reaches here.
      * `detail` plus a `Retry-After` -- SuperDocs' own application 429, the
        monthly quota. Surfaced, not spun on: this build's whole position is
        that the platform's own signal is authoritative and our arithmetic does
        not overrule it.
      * plain text, no `Retry-After` -- an infrastructure 429 from something in
        front of SuperDocs. Repeatable.

    **What a retry could cost.** The spec's blanket "retry 502/503/504 and
    timeouts" is right for a stateless client and wrong here: a 502 can come
    from a gateway that had already passed the request upstream, so repeating a
    billable POST can pay twice and apply the same edit twice -- the exact
    failure `TransportFailure.never_sent` and the operation ledger exist to
    prevent. So an ambiguous failure is repeated only on GET, where nothing is
    billed and nothing changes. On a charged POST it is handed back, and the
    ledger records it as started-and-unconfirmed for a person to settle. Fewer
    automatic recoveries, no double charges; that trade is the point of the
    build.
    """
    if response.status not in _RETRYABLE_STATUS:
        return None

    stated = retry_after_seconds(response.headers)

    if response.status == 429:
        code = str(relay_error(response.body).get("code") or "")
        if code and code != "rate_limited":
            # Some other relay refusal that `stop_signal` did not name. Do not
            # invent a recovery for a code we do not understand.
            return None
        if not code and isinstance(response.body, dict) and "detail" in response.body \
                and stated is not None:
            return None  # SuperDocs' application 429: the monthly quota.
        # Either the relay's limiter or an infrastructure 429. A 429 is refused
        # before any work happens, so repeating it cannot be billed twice.
        return stated if stated is not None else backoff_seconds(attempt)

    if method.upper() == "GET":
        return stated if stated is not None else backoff_seconds(attempt)
    return None


def backoff_seconds(attempt: int, rand: Callable[[float, float], float] = random.uniform) -> float:
    """~1s, 2s, 4s, 8s, 16s, jittered. The jitter is not decoration: several
    agents started by the same crash would otherwise retry in lockstep and
    rebuild the burst that got them limited."""
    return min(_MAX_SLEEP_S, (2 ** max(0, attempt - 1)) * rand(0.5, 1.5))


def _encode_multipart(files: dict, fields: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body from {name: (filename, bytes)} plus
    plain fields. Returns (body, content_type).

    A fixed boundary would collide with content that happens to contain it, so
    it is derived from the payload -- deterministic for a given body, which
    keeps requests reproducible, and vanishingly unlikely to appear inside it.
    """
    import hashlib

    digest = hashlib.sha256()
    for name, (filename, content) in sorted(files.items()):
        digest.update(name.encode())
        digest.update(str(filename).encode())
        digest.update(content if isinstance(content, bytes) else str(content).encode())
    boundary = "----formdata" + digest.hexdigest()[:24]

    out = bytearray()
    for name, value in fields.items():
        out += f"--{boundary}\r\n".encode()
        out += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        out += str(value).encode("utf-8") + b"\r\n"
    for name, (filename, content) in files.items():
        if isinstance(content, str):
            content = content.encode("utf-8")
        out += f"--{boundary}\r\n".encode()
        out += (f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n').encode()
        out += f"Content-Type: {_guess_type(filename)}\r\n\r\n".encode()
        out += content + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def _guess_type(filename: str) -> str:
    import mimetypes

    return mimetypes.guess_type(str(filename))[0] or "application/octet-stream"


class HttpTransport:
    """Real transport. Imported lazily so the package needs no HTTP library
    installed to run its tests."""

    def __init__(self, api_key: str, base: str = BASE, timeout: float = 300.0,
                 *, attempts: int = 5, sleep: Callable[[float], None] = time.sleep,
                 using_relay: bool = False, daily_ration: int | None = None) -> None:
        self._key = api_key
        self._base = base
        # ~300s is the platform gateway timeout for synchronous requests.
        self._timeout = timeout
        self._attempts = max(1, attempts)
        # Injected for the same reason the transport itself is: a retry policy
        # that can only be tested by waiting is a retry policy nobody tests.
        self._sleep = sleep
        #: Whether calls go through the shared relay. Read by the agent, which
        #: has to plan against relay's daily ration as well as the account's
        #: monthly allowance.
        self.using_relay = using_relay
        self.daily_ration = daily_ration

    @property
    def base(self) -> str:
        """Where calls go. Public because a CLI that cannot say which of the two
        endpoints it is about to spend against is hiding the only fact that
        distinguishes them."""
        return self._base

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, **kw: Any) -> "HttpTransport":
        """The transport the environment describes -- own key, or the relay.

        The only place in the package that reads the environment, so there is
        one precedence rule rather than one per caller.
        """
        e = resolve(env)
        return cls(e.key, base=e.base, using_relay=e.using_relay,
                   daily_ration=e.daily_ration, **kw)

    def request(self, method: str, path: str, **kw: Any) -> Response:
        """Send, and repeat only what is safe to repeat. See `retry_wait`."""
        for attempt in range(1, self._attempts + 1):
            try:
                r = self._send(method, path, **kw)
            except TransportFailure as e:
                # `never_sent` is the whole question: a refused connection can
                # be repeated because it cannot have been billed. A read that
                # timed out cannot, unless the call was a GET.
                repeatable = e.never_sent or method.upper() == "GET"
                if attempt >= self._attempts or not repeatable:
                    raise
                self._sleep(backoff_seconds(attempt))
                continue
            stop_signal(r.status, r.body, r.headers)
            wait = retry_wait(r, method=method, path=path, attempt=attempt)
            if wait is None or attempt >= self._attempts:
                return r
            self._sleep(wait)
        raise AssertionError("unreachable: the loop returns or raises")  # pragma: no cover

    def _send(self, method: str, path: str, **kw: Any) -> Response:
        import urllib.error
        import urllib.request

        url = self._base + path
        headers = {"Authorization": f"Bearer {self._key}",
                   "User-Agent": USER_AGENT}
        data = None
        if "files" in kw:
            # Upload is multipart/form-data, not JSON. Encoded here rather than
            # with a library because this package has no dependencies -- and
            # because getting it wrong is invisible: the request still sends,
            # and the API answers 422 for a field it never received.
            data, content_type = _encode_multipart(kw["files"], kw.get("data", {}))
            headers["Content-Type"] = content_type
        elif "json" in kw:
            data = json.dumps(kw["json"]).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:
                raw = r.read()
                body = json.loads(raw) if raw and r.headers.get_content_type() == "application/json" else {"raw": raw}
                return Response(r.status, body, dict(r.headers))
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                body = json.loads(raw)
            except Exception:
                body = {"raw": raw.decode(errors="replace")}
            return Response(e.code, body, dict(e.headers or {}))
        except urllib.error.URLError as e:
            # Name the cause and the fix, and -- more importantly -- say whether
            # the request could have been billed, so the ledger can record the
            # truth rather than the convenient answer.
            never_sent = provably_never_sent(e)
            raise TransportFailure(
                f"could not reach {self._base} ({e.reason}). "
                + ("The connection was refused or the host did not resolve, so "
                   "the request never reached SuperDocs and was not billed — "
                   f"check network access to {self._base} and retry."
                   if never_sent else
                   "It is not known whether the request arrived, so it must not "
                   "be assumed unbilled — rerun and read what the operation "
                   "ledger reports about it."),
                never_sent=never_sent,
            ) from e
        except TimeoutError as e:
            # A read timeout is the ambiguous case by definition: the request
            # went out and the answer never came back.
            raise TransportFailure(
                f"no response from {self._base} within {self._timeout:.0f}s. "
                "SuperDocs may still be processing this — large documents and "
                "the deepest model settings take minutes — so the request may "
                "well have been accepted and billed. It is recorded as started "
                "and unconfirmed rather than retried.",
                never_sent=False,
            ) from e


#: What the upload endpoint parses each extension as. Verified against the live
#: API 2026-08-20: the **filename decides the parser**, not the bytes. HTML sent
#: as `report.docx` is answered `400 Invalid DOCX file: File is not a zip file`,
#: and the same bytes as `report.html` are accepted. `.txt` is accepted too and
#: parses the markup as literal text, which is worse than an error because it
#: succeeds.
_ZIP_EXTENSIONS = {".docx", ".xlsx", ".pptx", ".odt"}
_PDF_EXTENSIONS = {".pdf"}
_TEXT_EXTENSIONS = {".html", ".htm", ".txt", ".md", ".markdown", ".rtf"}


def check_upload_name(filename: str, content: bytes) -> None:
    """Refuse a filename whose extension disagrees with the bytes.

    This is a deliberate hardcoded defence sitting in front of the intelligent
    path, not a guess about what the caller meant. The live API decides how to
    parse an upload from the extension alone, so `agent.run(..., "contract.docx",
    html_bytes)` reads perfectly and fails at the platform with a message about
    zip files, which names neither the cause nor the fix. Worse, the mismatch
    that does NOT error — HTML uploaded as `.txt` — succeeds and quietly parses
    the markup as literal text, and nobody finds out until the export.

    So it is checked here, before anything is sent, and the error says which
    two things disagreed and both ways to make them agree.
    """
    import os

    ext = os.path.splitext(str(filename))[1].lower()
    if not ext:
        raise ValueError(
            f"'{filename}' has no file extension. SuperDocs chooses how to parse "
            "an upload from the extension, so give one — '.html' for HTML, "
            "'.docx' for a Word file, '.pdf' for a PDF.")

    looks_like_zip = content[:4] == b"PK\x03\x04"
    looks_like_pdf = content[:4] == b"%PDF"

    if ext in _ZIP_EXTENSIONS and not looks_like_zip:
        raise ValueError(
            f"'{filename}' is named as a Word-family file but the bytes are not "
            "a zip archive, and SuperDocs parses uploads by extension — it would "
            "answer '400 Invalid DOCX file: File is not a zip file'. Either send "
            "the real .docx bytes, or rename this to '.html' if it is HTML.")
    if ext in _PDF_EXTENSIONS and not looks_like_pdf:
        raise ValueError(
            f"'{filename}' is named as a PDF but the bytes do not begin with "
            "'%PDF'. Send the real PDF bytes, or rename it to match what it is.")
    if ext in _TEXT_EXTENSIONS and (looks_like_zip or looks_like_pdf):
        raise ValueError(
            f"'{filename}' is named as text but the bytes are a "
            f"{'zip archive (a .docx, most likely)' if looks_like_zip else 'PDF'}. "
            "This would be accepted and parsed as literal text rather than as a "
            "document — rename it to match its contents.")


def pending_changes(job_body: dict) -> list[dict]:
    """Read the proposed changes off a job, whatever shape they arrive in.

    Two shapes exist and both are real:
      * `GET /v1/jobs/{id}` returns `metadata.pending_changes` as a plain LIST
        of change dicts. Verified against the live API 2026-08-19.
      * The SSE `proposed_change_batch` event delivers an envelope whose
        `content` is a JSON-encoded STRING needing a second parse.

    This lives in the client because both builds need it, and the copy that had
    it written separately handled only the envelope -- so it crashed on the
    shape the polling path actually returns.
    """
    meta = job_body.get("metadata") or {}
    pending = meta.get("pending_changes")
    if pending is None:
        for event in meta.get("intermediate_responses", []) or []:
            if event.get("type") == "proposed_change_batch":
                return parse_proposed_changes(event)
        return []
    if isinstance(pending, list):
        return list(pending)
    if isinstance(pending, str):
        return parse_proposed_changes({"content": pending})
    return parse_proposed_changes(pending)


def parse_proposed_changes(envelope: dict) -> list[dict]:
    """Trap 1. The batch arrives as a JSON string inside `content`.

    A single-change turn still arrives as a one-element `changes[]`, so this
    always returns a list and never special-cases the singular form.
    """
    content = envelope.get("content")
    if content is None:
        return list(envelope.get("changes", []))
    batch = json.loads(content) if isinstance(content, str) else content
    return list(batch.get("changes", []))


class SuperDocsClient:
    def __init__(self, transport: Transport, sleep: Callable[[float], None] = time.sleep) -> None:
        self._t = transport
        self._sleep = sleep
        #: Set once the platform has said the allowance is exhausted, including
        #: when it said so on a free call that was allowed to complete anyway.
        self.quota_exhausted = False

    @property
    def daily_ration(self) -> int | None:
        """Operations the transport may spend today, if something below it caps
        that; None when nothing does. `getattr` rather than an attribute on the
        Protocol, so the injected fakes stay three lines long."""
        return getattr(self._t, "daily_ration", None)

    @property
    def using_relay(self) -> bool:
        return bool(getattr(self._t, "using_relay", False))

    def _check(self, r: Response, *, billable: bool = True) -> Response:
        """Raise on an error, and on the platform's own exhaustion signal.

        `billable=False` marks the free calls -- whoami and export. An exhausted
        allowance must not stop those: exports and downloads never cost
        operations, and the reserve exists precisely to promise that the work
        already done can still be exported. Raising here would break that
        promise at the exact moment it matters, turning "you always end up with
        a file" into "you end up with a session and an exception". The signal is
        still recorded, so the caller stops spending; it just does not block a
        call that costs nothing.
        """
        if r.status >= 400:
            raise SuperDocsError(r.status, r.body)
        if r.usage.get("quota_exhausted"):
            # The current request still completed; further billable ones will not.
            self.quota_exhausted = True
            if billable:
                raise QuotaExhausted(r.status, r.body)
        return r

    # --- call 0: the one authoritative balance read available to an agent key.
    def whoami(self) -> Response:
        # Free, and it is the call that tells you the allowance is gone. Being
        # refused by the exhaustion it exists to report would be absurd.
        return self._check(self._t.request("GET", "/v1/agents/whoami"),
                           billable=False)

    # --- call 1 of the contract: upload.
    def upload(self, session_id: str, filename: str, content: bytes) -> Response:
        check_upload_name(filename, content)
        return self._check(
            self._t.request(
                "POST", "/v1/documents/upload",
                files={"file": (filename, content)}, data={"session_id": session_id},
            )
        )

    # --- call 2: the edit instruction.
    def edit(self, session_id: str, message: str, approval_mode: str = "ask_every_time") -> Response:
        return self._check(
            self._t.request(
                "POST", "/v1/chat/async",
                json={"session_id": session_id, "message": message, "approval_mode": approval_mode},
            )
        )

    def job(self, job_id: str) -> Response:
        return self._check(self._t.request("GET", f"/v1/jobs/{job_id}"))

    def poll_job(self, job_id: str, deadline_s: float = 600.0, interval_s: float = 2.0,
                 on_wait: Callable[[float, str], None] | None = None) -> Response:
        """Trap 2. Silence is still processing.

        Returns as soon as the job is terminal *or* is waiting on a human. Gives
        up only at an explicit deadline, and says how long it waited -- a slow
        job is never reported as a crash.
        """
        waited = 0.0
        while True:
            r = self.job(job_id)
            status = r.body.get("status", "")
            if status in _TERMINAL or status == _NEEDS_HUMAN:
                return r
            if waited >= deadline_s:
                raise TimeoutError(
                    f"job {job_id} was still '{status}' after {waited:.0f}s. "
                    "That is a deadline this client imposed, not a platform failure -- "
                    "the job may still be running."
                )
            if on_wait:
                on_wait(waited, status)
            self._sleep(interval_s)
            waited += interval_s

    # --- call 3: approve, item by item.
    def approve(self, session_id: str, job_id: str, decisions: list[dict]) -> Response:
        """`decisions` is a list of {change_id, approved, feedback?}. Sent as a
        batch so a mixed approve/deny turn is one request, not one per change."""
        return self._check(
            self._t.request(
                "POST", f"/v1/chat/{session_id}/approve",
                json={"job_id": job_id, "approved": True, "changes": decisions},
            )
        )

    # --- call 4: export. Free, per the docs, and so never priced.
    def export(self, session_id: str, fmt: str = "docx") -> Response:
        """Free per the docs, so an exhausted allowance never blocks it."""
        return self._check(
            self._t.request("POST", "/v1/documents/export",
                            json={"session_id": session_id, "format": fmt}),
            billable=False,
        )

    @staticmethod
    def export_warnings(r: Response) -> list:
        """Exports can succeed with non-fatal issues, carried base64-encoded in
        `X-Export-Warnings`. Surfaced rather than swallowed -- a dropped field
        code is exactly the kind of thing a user should be told about."""
        import base64

        header = r.headers.get("X-Export-Warnings")
        if not header:
            return []
        try:
            return json.loads(base64.b64decode(header))
        except Exception:
            return []
