"""Split a master document into separate clean `.docx` parts.

Four routes, one rule: a part is never handed over unverified. `/split` is free
and shows what the cut would produce; `/export` produces it and refuses success
unless the parts reconstruct the master block, heading and character for each.
The master's content lives in memory; only the parts and the log reach disk.

See use-cases/doc-splitter/README.md § "How it splits".
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from service import blocks as block_reader
from service import slicing
from service.cutting import Cut
from service.settings import Settings, get_settings
from service.store import Store, as_csv

UI_DIR = Path(__file__).resolve().parent.parent / "ui" / "dist"
"""The built React app. Served from the same origin as the API, so there is no
CORS, no second port and one thing to start."""


@dataclass
class Master:
    """One uploaded document, in memory."""

    id: str
    filename: str
    document_hash: str
    blocks: list[block_reader.Block] = field(default_factory=list)
    html: str = ""
    """The parsed document, as SuperDocs returned it. The UI renders exactly
    this, so what a reviewer points at and what gets cut are the same markup."""
    page_setup: dict[str, Any] = field(default_factory=dict)
    """Real paper size and margins from the `.docx`. The API carries no page or
    line numbers, so the preview paginates at these dimensions itself."""


class Documents:
    """Open masters, capped and evicted oldest-first. A master is megabytes of
    parsed HTML; not writing them down means capping how many RAM holds."""

    MAX = 6

    def __init__(self) -> None:
        self._open: dict[str, Master] = {}

    def add(self, master: Master) -> Master:
        self._open[master.id] = master
        while len(self._open) > self.MAX:
            self._open.pop(next(iter(self._open)))
        return master

    def get(self, document_id: str) -> Master | None:
        return self._open.get(document_id)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = Store(settings.database_path)
    store.setup()
    documents = Documents()

    app = FastAPI(
        title="Split a Document",
        version="0.1.0",
        summary=(
            "Cut a master document into separate clean .docx parts, "
            "and prove nothing was lost."
        ),
    )
    app.state.settings = settings
    app.state.store = store
    app.state.documents = documents

    @app.get("/health")
    def health() -> dict[str, Any]:
        missing = settings.missing_requirements()
        return {
            "status": "ok",
            "degraded": bool(missing),
            "missing_configuration": missing,
            "max_parts": settings.max_parts,
            "verify_coverage": settings.verify_coverage,
            "ui": UI_DIR.joinpath("index.html").exists(),
            "how_it_splits": (
                "Stateless HTML slicing plus one export per part. There is no split "
                "endpoint in the SuperDocs API and none is needed — export accepts a "
                "raw html body, so the master is never copied or mutated."
            ),
            "limitation": (
                "Split points come from real Word heading styles. A .docx yields "
                "headings; a .pdf or .md yields none, and the document can still be "
                "split — at block boundaries rather than headings."
            ),
        }

    @app.post("/upload")
    async def upload(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        """Master document in, addressable blocks out. Free — the parsed HTML
        comes back on the upload response, so no second call reads the structure."""
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="the uploaded file was empty")
        if not settings.superdocs_api_key:
            raise HTTPException(
                status_code=503,
                detail=(
                    "SUPERDOCS_API_KEY is not set. The document cannot be parsed into "
                    "blocks without it, so there is nothing to mark split points on."
                ),
            )

        from service._portable.superdocs_client import SuperDocsClient

        session_id = f"split-{uuid.uuid4()}"
        with SuperDocsClient(
            api_key=settings.superdocs_api_key,
            base_url=settings.superdocs_base_url,
            timeout_s=settings.sd_timeout_s,
        ) as client:
            result = client.upload_document(
                session_id=session_id, filename=file.filename or "master.docx", data=data
            )

        parsed = block_reader.parse(result.html)
        if not block_reader.flow(parsed):
            raise HTTPException(
                status_code=422,
                detail="no addressable blocks came back for this document — it cannot be split",
            )

        master = documents.add(
            Master(
                id=session_id,
                filename=file.filename or "master.docx",
                document_hash=hashlib.sha256(data).hexdigest(),
                blocks=parsed,
                html=result.html,
                page_setup=dict(getattr(result, "page_setup", {}) or {}),
            )
        )
        return {"document_id": master.id, **_outline(master)}

    @app.post("/split")
    def split(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """What the cut would produce. Free — nothing is exported, so moving a
        split point around is not billed."""
        master, cuts = _request(documents, body)
        return _preview(master, slicing.split(master.blocks, cuts))

    @app.post("/export")
    def export(body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Produce the parts, then check them before saying they are parts."""
        master, cuts = _request(documents, body)
        parts = slicing.split(master.blocks, cuts)
        if len(parts) > settings.max_parts:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{len(parts)} parts exceeds MAX_PARTS={settings.max_parts}. Each part "
                    "costs one export operation; raise the limit deliberately."
                ),
            )
        report = slicing.coverage(master.blocks, parts)
        if settings.verify_coverage and not report.complete:
            # Before spending anything: exported parts that don't reconstruct the
            # master would look right and not be.
            raise HTTPException(
                status_code=422,
                detail=f"refusing to export — {report.summary}",
            )
        if not settings.superdocs_api_key:
            raise HTTPException(
                status_code=503, detail="SUPERDOCS_API_KEY is not set, so parts cannot be exported"
            )

        from service._portable.superdocs_client import SuperDocsClient

        folder = settings.data_dir / "parts"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
        written: list[dict[str, Any]] = []
        durable: list[str] = []

        with SuperDocsClient(
            api_key=settings.superdocs_api_key,
            base_url=settings.superdocs_base_url,
            timeout_s=settings.sd_timeout_s,
        ) as client:
            for part in parts:
                name = (
                    f"{_slug(master.filename, is_filename=True)}-{stamp}"
                    f"-part{part.number}-{_slug(part.title)}.docx"
                )
                exported = client.export(html=part.html, fmt="docx", filename=name)
                target = _free_name(folder, name)
                target.write_bytes(exported.content)

                # Each part becomes a real SuperDocs document, not just bytes —
                # so a reviewer can reopen, edit or share it. Its OWN session:
                # the durable id is per session slot, so one session for all
                # parts hands them the same id and each overwrites the last
                # (measured — three parts, one id, two lost).
                holder = f"{master.id}-part{part.number}-{uuid.uuid4().hex[:8]}"
                registered = client.upload_document(
                    session_id=holder, filename=name, data=exported.content
                )
                durable.append(registered.durable_document_id)

                written.append(
                    {
                        "part": part.number,
                        "title": part.title,
                        "path": f"data/parts/{target.name}",
                        "document_id": registered.durable_document_id,
                        "blocks": len(part.blocks),
                        "headings": part.headings,
                        "characters": len(part.text),
                        "warnings": exported.warnings,
                    }
                )

            # Gathered into one session so the set opens together. Free, and it
            # shares the documents in rather than copying.
            gathered = ""
            if durable:
                gathered = f"{master.id}-parts"
                try:
                    client.open_documents(session_id=gathered, document_ids=durable)
                except Exception:
                    # The parts exist and are exported either way; losing the
                    # one-session convenience must not fail a verified split.
                    gathered = ""

        store.record(
            [
                {
                    "document": master.filename,
                    "document_hash": master.document_hash,
                    "part_number": row["part"],
                    "part_title": row["title"],
                    "blocks": row["blocks"],
                    "headings": row["headings"],
                    "characters": row["characters"],
                    "file": row["path"],
                    "coverage_ok": report.complete,
                    "coverage": report.summary,
                }
                for row in written
            ]
        )
        return {
            "document_id": master.id,
            "parts": written,
            "coverage": _coverage(report),
            "session_with_all_parts": gathered,
        }

    @app.post("/log/download")
    def download_log() -> dict[str, Any]:
        rows = store.entries()
        if not rows:
            raise HTTPException(status_code=404, detail="nothing has been split yet")
        folder = settings.data_dir / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        target = _free_name(folder, f"split-log-{datetime.now(UTC):%Y%m%d-%H%M%S}.csv")
        target.write_text(as_csv(rows), encoding="utf-8")
        return {"path": f"data/logs/{target.name}", "entries": len(rows)}

    # ── the page ─────────────────────────────────────────────────────────
    @app.get("/assets/{name:path}")
    def asset(name: str) -> Any:
        """A route, not a `StaticFiles` mount: a mount is created at start-up
        only if `ui/dist` exists, so in development it would be missing all
        process."""
        target = (UI_DIR / "assets" / name).resolve()
        root = (UI_DIR / "assets").resolve()
        # A path parameter is untrusted input.
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(status_code=404, detail="Not Found")
        media, _ = mimetypes.guess_type(target.name)
        return FileResponse(target, media_type=media or "application/octet-stream")

    @app.get("/", response_class=HTMLResponse)
    def index() -> Any:
        page = UI_DIR / "index.html"
        if page.exists():
            return FileResponse(page, media_type="text/html")
        return HTMLResponse(_not_built(), status_code=200)

    @app.exception_handler(404)
    def missing(_request: Any, exc: Any) -> JSONResponse:
        return JSONResponse(
            {"detail": getattr(exc, "detail", None) or "Not Found"}, status_code=404
        )

    return app


# ── helpers ──────────────────────────────────────────────────────────────


def _request(documents: Documents, body: dict[str, Any] | None) -> tuple[Master, list[Cut]]:
    payload = body or {}
    master = documents.get(str(payload.get("document_id") or ""))
    if master is None:
        raise HTTPException(
            status_code=404,
            detail="that document is no longer open — the service restarted. Upload it again.",
        )
    cuts: list[Cut] = []
    for item in payload.get("cuts") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunk_id") or "")
        if chunk_id:
            cuts.append(Cut(chunk_id=chunk_id, offset=int(item.get("offset") or 0)))
    return master, cuts


def _outline(master: Master) -> dict[str, Any]:
    """Every block a split point could be marked on."""
    content = block_reader.flow(master.blocks)
    return {
        "filename": master.filename,
        # The document itself, so the UI renders it at real page size and lets
        # someone point at a word rather than tick a checkbox.
        "html": master.html,
        "page_setup": master.page_setup,
        # chunk_id and index only. The UI renders the document itself, so a
        # per-block text preview would ship the contract twice for a field
        # nothing reads. The outline just orders the cuts.
        "blocks": [
            {"chunk_id": block.chunk_id, "index": index}
            for index, block in enumerate(content)
        ],
        "headings": sum(1 for block in content if block.heading_level),
        "furniture": len(block_reader.furniture(master.blocks)),
    }


def _preview(master: Master, parts: list[slicing.Part]) -> dict[str, Any]:
    report = slicing.coverage(master.blocks, parts)
    return {
        "document_id": master.id,
        "parts": [
            {
                "part": part.number,
                "title": part.title,
                "blocks": len(part.blocks),
                "headings": part.headings,
                "characters": len(part.text),
                "first": part.blocks[0].chunk_id if part.blocks else "",
            }
            for part in parts
        ],
        "coverage": _coverage(report),
    }


def _coverage(report: slicing.Coverage) -> dict[str, Any]:
    return {
        "complete": report.complete,
        "summary": report.summary,
        "master_blocks": report.master_blocks,
        "part_blocks": report.part_blocks,
        "master_headings": report.master_headings,
        "part_headings": report.part_headings,
        "master_characters": report.master_chars,
        "part_characters": report.part_chars,
        "blocks_cut": report.blocks_cut,
        "headings_cut": report.headings_cut,
        "dropped": report.dropped,
        "duplicated": report.duplicated,
        "repeated_furniture": report.repeated_furniture,
    }


def _slug(text: str, *, is_filename: bool = False) -> str:
    """A filename fragment. Untrusted — from the document.

    `is_filename` matters: `Path("1. Parties").stem` is "1" (everything after the
    first dot reads as a suffix), which threw section titles out of part names.
    """
    base = Path(text).stem if is_filename else text
    return re.sub(r"[^A-Za-z0-9_-]+", "-", base or "part").strip("-.")[:40] or "part"


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    stem, suffix = target.stem, target.suffix
    nth = 2
    while target.exists():
        target = folder / f"{stem}-{nth}{suffix}"
        nth += 1
    return target


def _not_built() -> str:
    """Only reachable if `ui/index.html` is missing from the image."""
    return (
        "<!doctype html><meta charset='utf-8'><title>Split a Document</title>"
        "<p style='font:14px sans-serif;margin:60px auto;max-width:38em'>"
        "The service is running — <code>curl localhost:8080/health</code> answers — "
        "but <code>ui/index.html</code> is missing from this image.</p>"
    )


app = create_app()
