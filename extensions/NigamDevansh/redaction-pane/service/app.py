"""The one process: it serves the task pane to Word and answers the pane's API.

Both halves over the same HTTPS origin: Office loads the pane from
`SourceLocation` and the pane calls back for scanning and redaction. Two origins
would mean CORS, a second certificate and a second thing to start.

`/health` reports which detection tiers this configuration can run and which
credentials are missing, so a reviewer whose scan finds nothing can tell "clean
document" from "no model key".

Six routes, one rule: nothing here removes text. `/scan` proposes,
`/candidates/{id}/dismiss` records a refusal, `/candidates/{id}/redacted`
records a removal Word already performed under a human click. There is no path
that edits a document on its own.

See extensions/redaction-pane/README.md § "The API, and what it cannot do".
"""

from __future__ import annotations

import hashlib
import html as html_escape
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from service import blocks as block_reader
from service import export as exporting
from service import markers
from service import scanner as scanning
from service.review import Candidate, Review, Session
from service.settings import Settings, get_settings
from service.store import Store, as_csv

PANE_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"
"""The built task pane. Absent until `npm run build`; the app serves an honest
placeholder, because a 404 inside Word's task pane is a blank white rectangle."""

COVERS = (
    "Visible document text: body, headers, footers, footnotes, endnotes, comments, "
    "and the contents of tracked deletions."
)
DOES_NOT_COVER = (
    "Document properties and file metadata (docProps/*). They are checked after "
    "export and reported, never modified."
)

UNIDENTIFIED = "unidentified reviewer"
"""No sign-in here, and inventing one would be worse than admitting it. The pane
sends a name the person types; this records it, labelled self-declared and
unverified everywhere it is shown. Presenting it as a verified identity would be
a false certification."""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = Store(settings.database_path)
    store.setup()
    review = Review()
    scanner = scanning.Scanner(settings)

    app = FastAPI(
        title="Redaction Pane",
        version="0.1.0",
        summary="Word add-in: scan, confirm, redact, export — with a human click on every removal.",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.review = review
    app.state.scanner = scanner

    @app.get("/health")
    def health() -> dict[str, Any]:
        """What this instance can and cannot do right now."""
        missing = settings.missing_requirements()
        return {
            "status": "ok",
            "tiers": settings.tiers,
            # The tier-3 provider this image was built for, and the default. The
            # image bakes one provider's SDK (the LLM_PROVIDER build arg); to
            # switch, set LLM_PROVIDER and rebuild (make up).
            "llm_provider": settings.llm_provider,
            "llm_provider_default": "openai",
            "degraded": bool(missing),
            "missing_configuration": missing,
            "pane_built": PANE_DIR.joinpath("taskpane.html").exists(),
            "markers": markers.BY_CATEGORY,
            "verify_export": settings.verify_export,
            # Said here as well as in the pane and the audit log. A boundary
            # stated once is a boundary somebody misses.
            "covers": COVERS,
            "does_not_cover": DOES_NOT_COVER,
        }

    # ── scan ─────────────────────────────────────────────────────────────
    @app.post("/scan")
    async def scan(
        file: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "",
        reviewer: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        """The open document → candidates, all pending. `session_id` is passed
        back on a re-scan so the same review continues; it refers to memory in
        this process, not a row — reload the pane and it is gone."""
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="the uploaded file was empty")

        who = (reviewer or "").strip() or UNIDENTIFIED
        try:
            outcome = scanner.scan(data)
        except block_reader.UnreadableDocument as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc

        session = review.get(session_id) if session_id else None
        if session is None:
            session = review.open(
                filename=file.filename or "document.docx",
                document_hash=hashlib.sha256(data).hexdigest(),
                reviewer=who,
            )
        session.reviewer = who

        fresh = review.add(session, scanning.candidates(outcome))
        return {
            "session_id": session.id,
            "candidates": [_candidate(item) for item in session.candidates.values()],
            "scan": {
                # No "blocks" count: it is exactly `sum(coverage.values())`, and
                # the breakdown answers every question the total does.
                "coverage": outcome.coverage,
                "tiers": outcome.tiers,
                "llm_blocks": outcome.llm_blocks,
                "dropped_unverifiable": outcome.dropped_unverifiable,
                "input_tokens": outcome.input_tokens,
                "output_tokens": outcome.output_tokens,
                "new": len(fresh),
                "notes": outcome.notes,
            },
            "document_hash": session.document_hash,
            "covers": COVERS,
            "does_not_cover": DOES_NOT_COVER,
        }

    # ── decisions ────────────────────────────────────────────────────────
    @app.post("/candidates/{candidate_id}/dismiss")
    def dismiss(candidate_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Somebody looked at it and said leave it. Logged, not just held in
        memory: "nobody reviewed this" and "a reviewer decided it stays" differ,
        and only the log can tell them apart afterwards."""
        session, candidate = _find(review, candidate_id)
        who = _actor(body) or session.reviewer
        review.decide(candidate, "dismissed")
        _log(store, session, candidate, who, action="dismissed",
             detail=str((body or {}).get("reason") or ""))
        return {"candidate": _candidate(candidate)}

    @app.post("/candidates/{candidate_id}/redacted")
    def redacted(candidate_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Word has already replaced the text; this is the record of it. The
        order matters: the pane calls Word first and this second, so the log only
        describes a removal that happened. Recording intent first would claim a
        document clean when the write failed."""
        session, candidate = _find(review, candidate_id)
        payload = body or {}
        who = _actor(payload) or session.reviewer
        failed = payload.get("failed") or []
        applied = int(payload.get("applied") or 0)

        if failed or applied == 0:
            reason = str(
                (failed[0] or {}).get("reason") if failed else "Word replaced no occurrences"
            )
            review.decide(candidate, "failed")
            _log(store, session, candidate, who, action="failed", detail=reason)
            return {"candidate": _candidate(candidate), "error": reason}

        review.decide(candidate, "applied")
        # The marker the pane actually wrote, not the candidate's. A tracked
        # deletion is removed by accepting the change, so no marker enters the
        # document — a log naming one would not match the file.
        written = payload.get("marker")
        _log(
            store, session, candidate, who, action="redacted",
            marker=candidate.marker if written is None else str(written),
            detail=str(payload.get("detail") or "") or f"{applied} occurrence(s) replaced",
        )
        return {"candidate": _candidate(candidate)}

    @app.post("/candidates/{candidate_id}/revert")
    def revert(candidate_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        """A reviewer changed their mind; the row returns to pending. The earlier
        entry is not deleted: the text was removed and then put back, and a log
        that erased the removal would be false about the past. So a `reverted`
        row is appended. Called AFTER Word restores the text, like `/redacted`."""
        session, candidate = _find(review, candidate_id)
        payload = body or {}
        who = _actor(payload) or session.reviewer
        was = candidate.status
        if was == "pending":
            raise HTTPException(status_code=409, detail="this candidate has not been decided")

        review.decide(candidate, "pending")
        _log(
            store, session, candidate, who, action="reverted", marker="",
            detail=str(payload.get("detail") or "") or f"undone by the reviewer (was {was})",
        )
        return {"candidate": _candidate(candidate)}

    # ── the log ──────────────────────────────────────────────────────────
    @app.post("/export")
    async def export(
        file: Annotated[UploadFile, File()],
        session_id: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        """A clean copy, verified before it is offered. Where the in-place path
        edits the open document, this produces a separate file through SuperDocs
        — the only path that reaches text Word cannot edit in place — then opens
        it as a zip and searches every part for every confirmed string. A file
        that does not verify is reported as a failure and still written, so the
        reviewer can see what came back."""
        # The pane re-sends the document rather than the service holding scan
        # bytes: a .docx with exhibits is megabytes, one per session would grow
        # the process, and the pane's copy is current where the scan's is stale.
        session = review.get(session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "this review is no longer open — the pane was reloaded or the "
                    "service restarted. Scan again."
                ),
            )
        if not settings.superdocs_api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "SUPERDOCS_API_KEY is not set, so a clean copy cannot be produced. "
                    "Scanning and in-place redaction are unaffected."
                ),
            )

        items = {
            candidate.text: candidate.marker
            for candidate in session.candidates.values()
            if candidate.status == "applied"
        }
        if not items:
            raise HTTPException(
                status_code=409, detail="nothing has been confirmed for redaction yet"
            )

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="the uploaded file was empty")

        from service._portable.superdocs_client import SuperDocsClient

        with SuperDocsClient(
            api_key=settings.superdocs_api_key,
            base_url=settings.superdocs_base_url,
            timeout_s=settings.sd_timeout_s,
        ) as client:
            outcome = exporting.run(
                client=client,
                session_id=session.id,
                filename=session.filename,
                data=data,
                items=items,
            )

        written = ""
        if outcome.content:
            folder = settings.data_dir / "exports"
            folder.mkdir(parents=True, exist_ok=True)
            target = _free_name(
                folder,
                f"redacted-{_slug(session.filename)}-{datetime.now(UTC):%Y%m%d-%H%M%S}",
                suffix=".docx",
            )
            target.write_bytes(outcome.content)
            written = f"data/exports/{target.name}"
            _log_export(store, session, outcome, written)

        report = outcome.report
        return {
            "clean": outcome.clean,
            "path": written,
            "approved": outcome.approved,
            "rejected": outcome.rejected,
            "warnings": outcome.warnings,
            "verification": None
            if report is None
            else {
                "summary": report.summary,
                "parts_checked": report.parts_checked,
                "markers_found": report.markers_found,
                "residue": [
                    {"text": hit.text, "part": hit.part} for hit in report.residue
                ],
                "property_residue": [
                    {"text": hit.text, "part": hit.part} for hit in report.property_residue
                ],
            },
            "does_not_cover": DOES_NOT_COVER,
        }

    @app.post("/audit/download")
    def download(document: str = "") -> dict[str, Any]:
        """Write the log to a file beside the database and say where it went.

        Written by the service, not downloaded by the pane, because a Word task
        pane is a sandboxed iframe: `window.open` is blocked and `<a download>`
        on a blob URL is inert, both failing silently. The service has a writable
        host-mounted directory, so it writes there. A new timestamped file each
        time — overwriting would destroy a log exported earlier.
        """
        resolved = _resolve_document(store, document)
        report = store.report(resolved)
        entries = report.get("entries") or []

        folder = settings.data_dir / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        stem = (
            f"redaction-log-{_slug(str(report.get('document') or 'document'))}"
            f"-{resolved[:8]}-{datetime.now(UTC):%Y%m%d-%H%M%S}"
        )
        # One file: the CSV. The coverage boundary it cannot carry is still at
        # `/audit.json` and in the pane — not lost, just not in the spreadsheet.
        target = _free_name(folder, stem, suffix=".csv")
        target.write_text(as_csv(report), encoding="utf-8")

        return {
            # Relative to the app folder `./data` is mounted from — a path the
            # reviewer can open, not the container's `/app/data`.
            "path": f"data/logs/{target.name}",
            "entries": len(entries),
        }

    @app.get("/audit.json")
    def audit_json(document: str = "") -> dict[str, Any]:
        return store.report(_resolve_document(store, document))

    @app.get("/audit", response_class=HTMLResponse)
    def audit(document: str = "") -> Any:
        """The log as a page, because it opens in a browser tab. `/audit.json`
        serves the same thing for machines; the person clicking "Audit log"
        wants to read it."""
        return HTMLResponse(_audit_page(store.report(_resolve_document(store, document))))

    # ── the pane ─────────────────────────────────────────────────────────
    @app.get("/taskpane.html", response_class=HTMLResponse)
    def taskpane() -> Any:
        """What Word's `SourceLocation` points at."""
        built = PANE_DIR / "taskpane.html"
        if built.exists():
            return FileResponse(built, media_type="text/html")
        return HTMLResponse(_not_built(), status_code=200)

    @app.get("/assets/{name:path}")
    def asset(name: str) -> Any:
        """A route, not a `StaticFiles` mount: a mount is created at start-up
        only if `ui/dist` exists, and in development the watcher writes it seconds
        later — so the mount would be missing all process. Per-request resolving
        has no such ordering."""
        target = (PANE_DIR / "assets" / name).resolve()
        root = (PANE_DIR / "assets").resolve()
        # Untrusted path parameter: `..%2f..%2fetc/passwd` is a real request, and
        # `resolve()` only guards once it is compared.
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        media, _ = mimetypes.guess_type(target.name)
        return FileResponse(target, media_type=media or "application/octet-stream")

    @app.exception_handler(404)
    def missing(_request: Any, exc: Any) -> JSONResponse:
        """A mistyped path gets "Not Found"; a real one keeps its reason. Exists
        so an unknown route returns JSON, not the pane's HTML with a 200 — but a
        flat `"Not Found"` also flattened every deliberate
        `HTTPException(404, detail=...)`, so "this review is no longer open, scan
        again" reached the reviewer as two useless words."""
        return JSONResponse(
            {"detail": getattr(exc, "detail", None) or "Not Found"}, status_code=404
        )

    return app


# ── helpers ──────────────────────────────────────────────────────────────


def _actor(body: dict[str, Any] | None) -> str:
    return str((body or {}).get("reviewer") or "").strip()


def _find(review: Review, candidate_id: str) -> tuple[Session, Candidate]:
    """A 404 here means the pane was reloaded and its review is gone. Said in
    those words, not a bare "not found", because that is the one confusing
    consequence of holding the review in memory."""
    found = review.candidate(candidate_id)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "this review is no longer open — the pane was reloaded or the "
                "service restarted. Scan again."
            ),
        )
    return found


def _log(
    store: Store,
    session: Session,
    candidate: Candidate,
    who: str,
    *,
    action: str,
    detail: str = "",
    marker: str | None = None,
) -> None:
    store.record(
        document=session.filename,
        document_hash=session.document_hash,
        reviewer=who or UNIDENTIFIED,
        action=action,
        text=candidate.text,
        category=candidate.category,
        part_type=candidate.part_type,
        chunk_id=candidate.chunk_id,
        char_start=candidate.char_start,
        char_end=candidate.char_end,
        marker=(marker if marker is not None else candidate.marker) if action == "redacted" else "",
        detail=detail,
    )


def _slug(name: str) -> str:
    """A filename fragment from a document name. Untrusted: it came from the
    open document, and `../../etc/passwd.docx` is a legal thing to call a file."""
    stem = Path(name).stem or "document"
    return re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")[:60] or "document"


def _log_export(store: Store, session: Session, outcome: Any, path: str) -> None:
    """One row for the export itself, so the log says a file left the building.
    `action` marks it apart from per-row decisions: nothing new was removed, an
    artefact was produced from removals already recorded."""
    store.record(
        document=session.filename,
        document_hash=session.document_hash,
        reviewer=session.reviewer,
        action="exported" if outcome.clean else "export_unverified",
        text=path,
        category="",
        part_type="",
        chunk_id="",
        char_start=0,
        char_end=0,
        detail=outcome.report.summary if outcome.report else "no verification ran",
    )


def _free_name(folder: Path, stem: str, suffix: str = ".json") -> Path:
    """A name nothing is using yet. A counter, because two downloads inside one
    second are not exotic — click, notice a typo, click again — and a timestamp
    alone would silently overwrite the first file."""
    candidate = folder / f"{stem}{suffix}"
    nth = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{nth}{suffix}"
        nth += 1
    return candidate


def _resolve_document(store: Store, document_hash: str) -> str:
    resolved = document_hash or store.latest_document() or ""
    if not resolved:
        raise HTTPException(status_code=404, detail="nothing has been redacted yet")
    return resolved


def _candidate(candidate: Candidate) -> dict[str, Any]:
    """One candidate as the pane reads it. The pane's `Candidate` type, exactly."""
    return {
        "id": candidate.id,
        "key": candidate.key,
        "category": candidate.category,
        "kind": candidate.kind,
        "detector": candidate.detector,
        "text": candidate.text,
        "sentence": candidate.sentence,
        "part_type": candidate.part_type,
        "chunk_id": candidate.chunk_id,
        "char_start": candidate.char_start,
        "char_end": candidate.char_end,
        "marker": candidate.marker,
        "status": candidate.status,
    }


def _audit_page(report: dict[str, Any]) -> str:
    """The redaction log, rendered. Escaped, because it prints document text: a
    contract containing `<script>` would otherwise run it in the reviewer's
    browser — untrusted input on the way out as much as in."""
    esc = html_escape.escape

    def where(row: dict[str, Any]) -> str:
        return (
            f"{row.get('part_type', '')} · {row.get('chunk_id', '')} "
            f"[{row.get('char_start', "")}-{row.get('char_end', "")}]"
        )

    def table(rows: list[dict[str, Any]], columns: list[tuple[str, Any]]) -> str:
        if not rows:
            return "<p class='none'>None.</p>"
        head = "".join(f"<th>{esc(label)}</th>" for label, _ in columns)
        cells = (
            "".join(f"<td>{esc(str(read(row)))}</td>" for _, read in columns) for row in rows
        )
        body = "".join(f"<tr>{row}</tr>" for row in cells)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

    get = lambda key: (lambda row: row.get(key, ""))  # noqa: E731
    name = esc(str(report.get("document") or "document"))
    digest = esc(str(report.get("document_hash") or ""))[:16]

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Redaction log — {name}</title>
<style>
 body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      max-width:920px;margin:40px auto;padding:0 20px;color:#1b1b1b}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px}}
 .meta{{color:#666;margin:0 0 20px}}
 code{{background:#f3f3f3;padding:1px 5px;border-radius:3px;font-size:12px}}
 table{{border-collapse:collapse;width:100%;font-size:13px}}
 th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #e6e6e6;vertical-align:top}}
 th{{color:#666;font-weight:600}}
 .none{{color:#888}}
 .boundary{{background:#fbf7e8;border:1px solid #e8dcae;padding:12px 14px;border-radius:6px;
           margin:24px 0;font-size:13px}}
</style></head>
<body>
  <h1>Redaction log</h1>
  {_nothing_recorded(report)}
  <p class="meta">{name} · <code>{digest}…</code> ·
     reviewed by {esc(str(report.get('reviewer') or ''))} (self-declared, unverified) ·
     first entry {esc(str(report.get('started_at') or ''))}</p>

  <h2>Removed</h2>
  {table(report.get('removed') or [],
         [("What", get("text")), ("Category", get("category")),
          ("From where", where), ("Replaced with", get("marker")),
          ("By", get("reviewer")), ("At", get("at"))])}

  <h2>Reviewed and left in place</h2>
  {table(report.get('dismissed') or [],
         [("What", get("text")), ("From where", where),
          ("By", get("reviewer")), ("At", get("at"))])}

  <h2>Removed, then put back</h2>
  {table(report.get('reverted') or [],
         [("What", get("text")), ("From where", where), ("Why", get("detail")),
          ("By", get("reviewer")), ("At", get("at"))])}

  <h2>Could not be removed</h2>
  {table(report.get('failed') or [],
         [("What", get("text")), ("From where", where), ("Why", get("detail")),
          ("By", get("reviewer")), ("At", get("at"))])}

  <div class="boundary">
    <b>What this log is.</b> A record of human decisions. Every removal listed
    above required a click on a row.<br>
    <b>Covers:</b> {esc(str(report.get('covers') or ''))}<br>
    <b>Does not cover:</b> {esc(str(report.get('does_not_cover') or ''))}
  </div>
</body></html>"""


def _nothing_recorded(report: dict[str, Any]) -> str:
    """"No entries" and "no such document" look identical otherwise — three empty
    tables read as "reviewed, nothing removed", the opposite of a mistyped hash.
    The pane disables the button until a decision exists; this is for someone
    arriving by URL."""
    if report.get("entries"):
        return ""
    return (
        "<div class='boundary'><b>No entries for this document.</b> Either nothing "
        "has been decided yet, or this is not a document this pane has worked on. "
        "It is not a statement that the document is clean.</div>"
    )


def _not_built() -> str:
    """Shown inside Word when the UI has not been built. A blank pane is the worst
    failure here — Office gives no error, just an empty rectangle — so the
    unbuilt pane says so, in the pane."""
    return """<!doctype html>
<html><head><meta charset="utf-8"><title>Redaction Pane</title>
<style>
 body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      margin:0;padding:20px;color:#1b1b1b}
 code{background:#f3f3f3;padding:2px 5px;border-radius:3px;font-size:12px}
 h1{font-size:15px;margin:0 0 12px}
 p{margin:0 0 10px;color:#444}
</style></head>
<body>
  <h1>The pane is not built yet</h1>
  <p>The service is running and Word reached it over HTTPS — that is the hard part.
     What is missing is the built UI.</p>
  <p><code>cd ui &amp;&amp; npm install &amp;&amp; npm run build</code></p>
  <p>Then reload the pane: <b>right-click inside it → Reload</b>.</p>
</body></html>"""


app = create_app()
