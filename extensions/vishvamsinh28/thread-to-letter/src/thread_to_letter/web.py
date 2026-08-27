"""The console.

One FastAPI app and one self-contained page. No build step, no npm.

It does two things a status page would not. It **shows every call it makes to SuperDocs**
— method, path, status, duration, billable or not — so the integration is visible rather
than asserted. And it **never spends on its own**: extraction is one operation and the
letter is another, and each waits for a click.

The gate is the point of the whole tool, so it is the middle of the screen: every
candidate commitment with its status, its quote, and a checkbox. What you tick is what
the letter says.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import draft as draft_mod
from . import extract as extract_mod
from . import letter as letter_mod
from .client import Client, SuperDocsError
from .commitments import Commitment, dangling_superseded, summarise
from .config import load_settings
from .injection import scan_thread
from .thread import Thread, load, parse_plain

_PAGE = Path(__file__).parent / "console.html"

EXPORT_FORMATS = ("docx", "pdf", "markdown", "html", "txt")
_SUFFIX = {"markdown": "md"}
_MEDIA = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf", "html": "text/html",
    "markdown": "text/markdown", "txt": "text/plain",
}


@dataclass
class State:
    thread: Thread | None = None
    thread_name: str = ""
    commitments: list[Commitment] = field(default_factory=list)
    chosen: set[str] = field(default_factory=set)
    letter_html: str = ""
    session_id: str = ""
    error: str | None = None
    busy: str = ""


class ConsoleService:
    """Holds one thread at a time. A worker thread does the two billable calls."""

    def __init__(self, threads_dir: str) -> None:
        self.settings = load_settings()
        self.threads_dir = Path(threads_dir)
        self.state = State()
        self._lock = threading.Lock()
        self._calls: list[dict[str, Any]] = []
        self._seq = 0

    # --- API-call recording ------------------------------------------------

    def _client(self) -> Client:
        return Client(self.settings.api_key, self.settings.base_url)

    def _absorb(self, client: Client) -> None:
        """Move the client's call log into the console's, numbering as we go."""
        with self._lock:
            for call in client.calls:
                self._seq += 1
                self._calls.append({
                    "seq": self._seq, "method": call.method, "path": call.path,
                    "status": call.status, "ms": call.ms, "note": call.note,
                    "billable": call.billable,
                })
            client.calls.clear()

    # --- commands ----------------------------------------------------------

    def available_threads(self) -> list[str]:
        if not self.threads_dir.exists():
            return []
        return sorted(p.name for p in self.threads_dir.iterdir()
                      if p.suffix.lower() in (".mbox", ".eml", ".txt"))

    def open_thread(self, name: str = "", pasted: str = "") -> None:
        thread = (
            parse_plain(pasted, source="pasted") if pasted.strip()
            else load(self.threads_dir / name)
        )
        if not thread.messages:
            raise ValueError("no messages could be read from that")
        self.state = State(thread=thread, thread_name=name or "pasted thread")

    def extract(self) -> None:
        state = self.state
        if state.thread is None:
            raise ValueError("open a thread first")
        state.busy = "Reading the thread for commitments…"
        state.error = None
        try:
            import hashlib

            digest = hashlib.sha256(state.thread.normalised.encode()).hexdigest()[:12]
            state.session_id = f"thread2letter-{digest}"
            with self._client() as client:
                result = extract_mod.extract(client, state.thread, state.session_id)
                self._absorb(client)
            state.commitments = result.commitments
            # Pre-tick the ones that are both firm and backed by real words. The
            # reviewer changes them; nothing is committed on their behalf.
            state.chosen = {c.quote for c in result.commitments if c.usable}
        except (SuperDocsError, ValueError) as exc:
            state.error = str(exc)
        finally:
            state.busy = ""

    def write_letter(self, shape: str) -> None:
        import datetime as _dt

        state = self.state
        if state.thread is None:
            raise ValueError("open a thread first")
        state.busy = "Writing the letter…"
        state.error = None
        try:
            confirmed = [c for c in state.commitments if c.quote in state.chosen]
            with self._client() as client:
                drafted = letter_mod.draft(
                    client, state.thread, confirmed, state.session_id, shape=shape,
                    today=_dt.date.today().strftime("%d %B %Y"),
                )
                self._absorb(client)
            state.letter_html = drafted.html
        except (SuperDocsError, ValueError) as exc:
            state.error = str(exc)
        finally:
            state.busy = ""

    def toggle(self, quote: str, on: bool) -> None:
        if on:
            self.state.chosen.add(quote)
        else:
            self.state.chosen.discard(quote)

    def export(self, fmt: str) -> tuple[bytes, str]:
        if fmt not in EXPORT_FORMATS:
            raise ValueError(f"format must be one of {', '.join(EXPORT_FORMATS)}")
        state = self.state
        if not state.letter_html:
            raise ValueError("write the letter first")
        stem = draft_mod._slug(state.thread.subject if state.thread else "letter")
        with self._client() as client:
            blob = client.export(html=state.letter_html, fmt=fmt,
                                 options={"filename": stem})
            self._absorb(client)
        return blob, f"{stem}.{_SUFFIX.get(fmt, fmt)}"

    def reply_draft(self, fmt: str, from_address: str) -> tuple[bytes, str]:
        state = self.state
        if state.thread is None or not state.letter_html:
            raise ValueError("write the letter first")
        blob, filename = self.export(fmt)
        confirmed = [c for c in state.commitments if c.quote in state.chosen]
        raw = draft_mod.build_reply(
            state.thread, confirmed, blob, fmt=fmt, from_address=from_address,
            stem=draft_mod._slug(state.thread.subject),
        )
        return raw, f"reply-{draft_mod._slug(state.thread.subject)}.eml"

    # --- reads -------------------------------------------------------------

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        state = self.state
        with self._lock:
            calls = [c for c in self._calls if c["seq"] > since]
            seq, billable = self._seq, sum(1 for c in self._calls if c["billable"])

        thread = state.thread
        return {
            "connection": {
                "base_url": self.settings.base_url,
                "live": self.settings.is_live,
                "label": "api.superdocs.app" if self.settings.is_live
                         else self.settings.base_url,
                "key": self.settings.redacted(),
                "operations": billable,
            },
            "threads": self.available_threads(),
            "thread": None if thread is None else {
                "name": state.thread_name,
                "subject": thread.subject,
                "participants": thread.participants,
                "messages": [
                    {"index": m.index, "sender": m.sender, "date": m.date,
                     "body": m.body}
                    for m in thread.messages
                ],
                "findings": [
                    {"kind": f.kind, "where": f.where, "excerpt": f.excerpt}
                    for f in scan_thread(thread)
                ],
            },
            "commitments": [
                {**c.to_public(), "chosen": c.quote in state.chosen}
                for c in state.commitments
            ],
            "counts": summarise(state.commitments) if state.commitments else {},
            "dangling": [
                {"party": c.party, "obligation": c.obligation, "due": c.due}
                for c in dangling_superseded(state.commitments)
            ],
            "letter_html": state.letter_html,
            "busy": state.busy,
            "error": state.error,
            "calls": calls,
            "call_seq": seq,
            "formats": list(EXPORT_FORMATS),
        }


def create_app(threads_dir: str = "threads") -> FastAPI:
    service = ConsoleService(threads_dir)
    app = FastAPI(title="thread to letter")

    def _run(fn: Any, *args: Any) -> None:
        threading.Thread(target=fn, args=args, daemon=True).start()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _PAGE.read_text(encoding="utf-8")

    @app.get("/api/state")
    def state(since: int = 0) -> dict[str, Any]:
        return service.snapshot(since)

    @app.post("/api/open")
    def open_thread(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        try:
            service.open_thread(payload.get("name", ""), payload.get("pasted", ""))
        except (ValueError, OSError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return {"ok": True}

    @app.post("/api/extract")
    def extract(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if service.state.busy:
            raise HTTPException(409, detail="already working")
        _run(service.extract)
        return {"started": True}

    @app.post("/api/letter")
    def letter(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        if service.state.busy:
            raise HTTPException(409, detail="already working")
        _run(service.write_letter, payload.get("shape", "letter"))
        return {"started": True}

    @app.post("/api/toggle")
    def toggle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        service.toggle(payload["quote"], bool(payload["on"]))
        return {"ok": True}

    @app.get("/api/export")
    def export(fmt: str = "docx") -> Response:
        try:
            blob, filename = service.export(fmt)
        except (ValueError, SuperDocsError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return Response(content=blob, media_type=_MEDIA.get(fmt, "application/octet-stream"),
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/api/reply")
    def reply(fmt: str = "docx", sender: str = "") -> Response:
        try:
            raw, filename = service.reply_draft(fmt, sender)
        except (ValueError, SuperDocsError) as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return Response(content=raw, media_type="message/rfc822",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.exception_handler(HTTPException)
    def _err(_r: Any, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app
