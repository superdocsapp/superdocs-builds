"""The HTTP surface the browser talks to.

The SuperDocs key lives here and never goes further. That is not a preference — it is the
first hard constraint in SuperDocs' own integration guidance, and it is why the inspector
never sees a second product: they use this application, and SuperDocs is plumbing behind it.

Photographs are served from our own database rather than by handing the browser the URL
SuperDocs returned. That URL is readable by anyone who holds it and never expires, so putting
it in a page, a browser history or a referrer header would leak a photograph of a client's
home. The browser gets `/api/photos/{id}` instead.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from psycopg import OperationalError
from pydantic import BaseModel, Field

from inspection_report.domain import catalogue
from inspection_report.domain.models import (
    Finding,
    Inspection,
    Inspector,
    Property,
    ReportStage,
)
from inspection_report.logging import get_logger, setup_logging
from inspection_report.photos.pipeline import MAX_UPLOAD_BYTES, PhotoRejected, clean
from inspection_report.phrasing import rail
from inspection_report.store import db, jobs
from inspection_report.superdocs.base import SuperDocsError
from inspection_report.templates import docx_html

_log = get_logger("inspection_report.api")

TEMPLATE_DIR = Path(os.environ.get("TEMPLATE_DIR", "templates"))
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5174").split(",")
    if o.strip()
]

app = FastAPI(
    title="Home-inspection report builder",
    description="Findings and photo evidence per inspection system, assembled into a "
    "formatted field report. Built on SuperDocs.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # never "*": this serves photographs of people's homes
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# The largest request body this API will consider, multipart overhead included. The photo
# pipeline's own cap is smaller; this is the outer wall, and it exists because by the time a
# route function runs, FastAPI has already parsed the multipart body and spooled it to disk.
# A cap enforced after that is not a cap — it only decides what error you get after paying
# the cost. This middleware runs before routing, so an oversized body is refused with a 413
# and never read.
MAX_REQUEST_BYTES = 12 * 1024 * 1024


@app.middleware("http")
async def _refuse_oversized_bodies(request: Any, call_next: Any) -> Any:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            length = int(declared)
        except ValueError:
            return Response(status_code=400, content="malformed content-length")
        if length > MAX_REQUEST_BYTES:
            _log.warning("request_too_large", extra={"declared": length})
            return Response(
                status_code=413,
                media_type="application/json",
                content=json.dumps(
                    {
                        "detail": (
                            f"the request body is {length // 1024} KB; this API accepts at "
                            f"most {MAX_REQUEST_BYTES // 1024} KB. A photograph should be "
                            f"well under that — reduce the camera resolution or crop it."
                        )
                    }
                ),
            )
    return await call_next(request)


# Set when the schema could not be brought up to date. Distinct from "the database was not
# reachable at boot", which is transient and recovers on its own — a migration that failed
# means the code and the schema disagree, and every request after it is suspect.
_SCHEMA_ERROR: str | None = None


@app.on_event("startup")
def _startup() -> None:
    global _SCHEMA_ERROR
    setup_logging(os.environ.get("LOG_FORMAT", "json"))
    try:
        with db.connect() as conn:
            db.apply_schema(conn)
        _SCHEMA_ERROR = None
        _log.info("schema_ready")
    except OperationalError as exc:
        # The database was not up yet. Degrade rather than refuse to boot — /health and the
        # catalogue still answer, /ready says no, and the next request reconnects.
        _log.error("database_unavailable", extra={"error": type(exc).__name__})
    except Exception as exc:  # pragma: no cover - depends on a live database
        # Anything else here is the schema itself failing, which used to be logged as
        # "database_unavailable" and looked like a blip. It is not: the code and the schema
        # disagree, and pretending otherwise is how a deployment serves a broken shape.
        _SCHEMA_ERROR = f"{type(exc).__name__}: {exc}"
        _log.error("schema_migration_failed", extra={"error": _SCHEMA_ERROR[:300]})


def get_conn() -> Any:
    """Hand the request a connection, and relabel *only* the failure this is qualified to name.

    A dependency that yields is also where FastAPI re-raises whatever the endpoint threw, so a
    catch-all here does not catch database problems — it catches everything, including the
    request-validation error that should have been a 422. It reported those as "the database
    is not reachable" while the database was serving every other request, which sends whoever
    reads it to the wrong system entirely.
    """
    try:
        with db.connect() as conn:
            yield conn
    except OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "the database is not reachable. If you are running this outside Docker, "
                "set DATABASE_URL; inside `docker compose up` it is set for you."
            ),
        ) from exc


# ------------------------------------------------------------------ schemas


class PropertyIn(BaseModel):
    address_line: str
    city: str
    postcode: str = ""
    year_built: int | None = None
    property_type: str = ""


class InspectorIn(BaseModel):
    name: str
    licence_number: str = ""
    firm_name: str = ""


class InspectionIn(BaseModel):
    property: PropertyIn
    inspector: InspectorIn
    inspected_on: str
    template_key: str = "buyer_summary"


class FindingIn(BaseModel):
    system_key: str
    severity_key: str
    location: str = ""
    observation: str = Field(min_length=1)
    recommendation: str = ""


# ------------------------------------------------------------------- routes


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up and serving.

    Deliberately does not touch the database. This build degrades rather than refusing to
    boot — the catalogue still answers without one — so a restart loop on a database blip
    would make an outage worse rather than better.
    """
    return {"status": "ok"}


@app.get("/ready")
def ready() -> Response:
    """Readiness: everything this needs is actually reachable.

    Separate from liveness because they answer different questions, and `/health` answering
    "ok" while every request 503s is how a green dashboard hides an outage. Anything routing
    traffic should watch this one.
    """
    if _SCHEMA_ERROR is not None:
        return Response(
            status_code=503,
            media_type="application/json",
            content=json.dumps({"status": "degraded", "schema": _SCHEMA_ERROR}),
        )
    try:
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.execute("SELECT count(*) AS n FROM schema_migrations")
            applied = int((cur.fetchone() or {"n": 0})["n"])
    except Exception as exc:
        _log.warning("not_ready", extra={"error": type(exc).__name__})
        return Response(
            status_code=503,
            media_type="application/json",
            content=json.dumps({"status": "degraded", "database": "unreachable"}),
        )
    return Response(
        status_code=200,
        media_type="application/json",
        content=json.dumps(
            {"status": "ready", "database": "reachable", "migrations_applied": applied}
        ),
    )


@app.get("/api/catalogue")
def get_catalogue() -> dict[str, Any]:
    """Systems, severities and the language rail's rules — everything the UI renders from."""
    return {
        "systems": [s.model_dump() for s in catalogue.systems()],
        "severities": [s.model_dump() for s in catalogue.severities()],
        "rail_rules": rail.describe_rules(),
        "formats": sorted(p.stem for p in TEMPLATE_DIR.glob("*.docx")),
    }


@app.get("/api/inspections")
def list_inspections(conn: Any = Depends(get_conn)) -> list[dict[str, Any]]:
    return [
        {**row, "id": str(row["id"]), "inspected_on": row["inspected_on"].isoformat()}
        for row in db.list_inspections(conn)
    ]


@app.post("/api/inspections", status_code=201)
def create_inspection(body: InspectionIn, conn: Any = Depends(get_conn)) -> dict[str, str]:
    import datetime as dt

    if body.template_key not in {p.stem for p in TEMPLATE_DIR.glob("*.docx")}:
        raise HTTPException(
            status_code=400,
            detail=f"unknown report format {body.template_key!r}. "
            f"Available: {sorted(p.stem for p in TEMPLATE_DIR.glob('*.docx'))}",
        )
    inspection = Inspection(
        property=Property(**body.property.model_dump()),
        inspector=Inspector(**body.inspector.model_dump()),
        inspected_on=dt.date.fromisoformat(body.inspected_on),
        template_key=body.template_key,
    )
    db.save_inspection(conn, inspection)
    return {"id": str(inspection.id)}


@app.get("/api/inspections/{inspection_id}")
def get_inspection(inspection_id: UUID, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    inspection = db.load_inspection(conn, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail="no inspection with that id")
    return _serialise(inspection)


@app.post("/api/inspections/{inspection_id}/findings", status_code=201)
def add_finding(
    inspection_id: UUID, body: FindingIn, conn: Any = Depends(get_conn)
) -> dict[str, str]:
    inspection = db.load_inspection(conn, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail="no inspection with that id")
    # Validate against the catalogue here, so an unknown key is a 400 naming the valid set
    # rather than a finding that renders into nothing later.
    try:
        catalogue.system(body.system_key)
        catalogue.severity(body.severity_key)
    except catalogue.CatalogueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    finding = Finding(**body.model_dump())
    db.insert_finding(conn, inspection_id=inspection_id, finding=finding)
    return {"id": str(finding.id)}


@app.delete("/api/inspections/{inspection_id}", status_code=204)
def delete_inspection(inspection_id: UUID, conn: Any = Depends(get_conn)) -> Response:
    """Remove an inspection and everything under it. There is no undo.

    Refused while a review is in flight: the worker is holding that inspection and deleting
    it underneath would leave a job running against a report that no longer exists.
    """
    live = jobs.latest_for(conn, inspection_id)
    if live is not None and not live.finished:
        raise HTTPException(
            status_code=409,
            detail="a review is running for this inspection. Wait for it to finish, then "
            "delete it.",
        )
    if not db.delete_inspection(conn, inspection_id):
        raise HTTPException(status_code=404, detail="no inspection with that id")
    return Response(status_code=204)


@app.delete("/api/findings/{finding_id}", status_code=204)
def delete_finding(finding_id: UUID, conn: Any = Depends(get_conn)) -> Response:
    """Remove one finding and its photographs."""
    if not db.delete_finding(conn, finding_id):
        raise HTTPException(status_code=404, detail="no finding with that id")
    return Response(status_code=204)


@app.delete("/api/photos/{photo_id}", status_code=204)
def delete_photo(photo_id: UUID, conn: Any = Depends(get_conn)) -> Response:
    """Remove one photograph.

    The bytes go too, unless another finding photographed the same thing — a blob is keyed
    by its content hash, so it is reclaimed only when nothing references it.
    """
    if not db.delete_photo(conn, photo_id):
        raise HTTPException(status_code=404, detail="no photograph with that id")
    return Response(status_code=204)


@app.post("/api/findings/{finding_id}/photos", status_code=201)
async def add_photo(
    finding_id: UUID,
    file: UploadFile = File(...),
    conn: Any = Depends(get_conn),
) -> dict[str, Any]:
    """Take a photograph in, clean it, and keep it.

    EXIF is stripped before anything is stored: a phone photograph of a house carries the
    house's coordinates, and this report goes to buyers, agents and lenders.
    """
    name = file.filename or "photo"
    try:
        # Chunked, and abandoned the moment it goes over. A request with no content-length
        # slips past the middleware above, so the cap is enforced here too rather than by
        # measuring a blob that has already been read.
        raw = await _read_capped(file, MAX_UPLOAD_BYTES, name)
        photo = clean(raw, filename=name)
    except PhotoRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from inspection_report.domain.models import Photo

    record = Photo(
        sha256=photo.sha256,
        filename=file.filename or "photo",
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        width=photo.width,
        height=photo.height,
    )
    db.save_photo(
        conn,
        finding_id=finding_id,
        photo=record,
        data=photo.data,
        thumbnail=photo.thumbnail,
    )
    return {
        "id": str(record.id),
        "sha256": photo.sha256,
        "stripped_exif": photo.stripped_exif,
        "width": photo.width,
        "height": photo.height,
    }


@app.get("/api/photos/{photo_id}")
def get_photo(photo_id: UUID, thumb: bool = False, conn: Any = Depends(get_conn)) -> Response:
    """Photographs are served from here, never by handing out the SuperDocs URL."""
    found = db.photo_bytes(conn, photo_id, thumbnail=thumb)
    if found is None:
        raise HTTPException(status_code=404, detail="no photograph with that id")
    data, mime = found
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=3600", "Referrer-Policy": "no-referrer"},
    )


@app.post("/api/check-phrasing")
def check_phrasing(body: dict[str, str]) -> dict[str, Any]:
    """Run the observational-language rail over a piece of text.

    Exposed so the interface can show an inspector the same verdict the gate will apply,
    while they are still typing, rather than after a rewrite has been proposed.
    """
    verdict = rail.check(body.get("text", ""))
    return {
        "clean": verdict.clean,
        "summary": verdict.summary(),
        "breaches": [
            {
                "rule_id": b.rule_id,
                "category": b.category,
                "matched": b.matched,
                "why": b.why,
                "suggest": b.suggest,
            }
            for b in verdict.breaches
        ],
    }


def _serialise(inspection: Inspection) -> dict[str, Any]:
    return {
        "id": str(inspection.id),
        "property": inspection.property.model_dump(),
        "inspector": inspection.inspector.model_dump(),
        "inspected_on": inspection.inspected_on.isoformat(),
        "template_key": inspection.template_key,
        "stage": str(inspection.stage),
        "findings": [
            {
                "id": str(f.id),
                "system_key": f.system_key,
                "severity_key": f.severity_key,
                "location": f.location,
                "observation": f.observation,
                "recommendation": f.recommendation,
                "plain_language": f.plain_language,
                # Photographs are referenced by our own id. The SuperDocs URL is never
                # handed to a browser.
                "photos": [
                    {"id": str(p.id), "caption": p.caption, "filename": p.filename}
                    for p in f.photos
                ],
            }
            for f in inspection.findings
        ],
    }


# --------------------------------------------------------- building the report
#
# The gate is three calls, not one, because a person holds it. `prepare` goes as far as the
# proposals and stops; `decisions` relays what the person decided; `export` produces the
# files and verifies them. Nothing holds a connection open waiting for a human.


# The fake stands in for a service that remembers sessions between requests, so it has to
# remember them too: one instance for the life of the process. A fresh one per request would
# lose the session between preparing a report and deciding on it — and would quietly make the
# offline application behave unlike the live one, which is the whole thing the fake exists to
# avoid. The live client is per-request because its state lives server-side.
_FAKE: Any = None


def _provider() -> str:
    """Which SuperDocs is behind this — the service, or the fake standing in for it.

    Reported to the interface rather than kept here, because the fake keeps its own
    operations budget and a countdown from an imaginary 10,000 is indistinguishable on screen
    from the real balance. A number that cannot be told apart from a true one is worse than
    no number.
    """
    return os.environ.get("PROVIDER", "fake").lower()


def _client() -> Any:
    global _FAKE
    from inspection_report.superdocs.fake import FakeSuperDocsClient
    from inspection_report.superdocs.live import LiveSuperDocsClient

    if _provider() == "live":
        return LiveSuperDocsClient(api_key=os.environ.get("SUPERDOCS_API_KEY", ""))
    if _FAKE is None:
        _FAKE = FakeSuperDocsClient()
    return _FAKE


def _with_image_lookup(client: Any, conn: Any) -> Any:
    """Let the offline exporter resolve photographs from our own record.

    Only the fake exposes an image resolver — the live service holds the bytes itself and
    needs nothing. Without this, an export after a restart silently loses every photograph
    whose upload was cached, because the fake never saw those bytes in this process.
    """
    resolver = getattr(client, "images", None)
    if resolver is not None:
        resolver.lookup = lambda url: db.photo_bytes_by_url(conn, url)
    return client


def _release(client: Any) -> None:
    """Close a live client; leave the shared fake open for the next request."""
    if client is not _FAKE:
        client.close()


async def _read_capped(file: UploadFile, limit: int, filename: str) -> bytes:
    """Read an upload, refusing it as soon as it exceeds ``limit``.

    The point is to stop at the cap rather than to discover afterwards that it was passed.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(256 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise PhotoRejected(
                f"{filename} is larger than the {limit // 1024} KB limit. Reduce the camera "
                f"resolution or crop the image."
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _session_id(inspection_id: UUID) -> str:
    """Derived, not stored: the same inspection always resumes the same session."""
    return f"inspection-{inspection_id.hex[:12]}"


def _template_html(key: str) -> str:
    """The local copy of a format, converted the way SuperDocs converts it.

    Formats are Word documents, so this is a conversion rather than a read. It is the
    fallback path: the report is normally built from the document SuperDocs hands back when
    the registered format is loaded — see ``_materialised_template``.
    """
    path = TEMPLATE_DIR / f"{key}.docx"
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"unknown report format {key!r}. "
            f"Available: {sorted(p.stem for p in TEMPLATE_DIR.glob('*.docx'))}",
        )
    return docx_html.from_path(path)


def _materialised_template(conn: Any, key: str) -> tuple[str, str]:
    """The skeleton to build on, and — honestly — where it came from.

    The format is registered with SuperDocs and the report is built on the document SuperDocs
    hands back, not on the local file. That is the round trip the whole design rests on:
    delete the template from the account and no report can be produced.

    Three paths, and the caller is told which one ran, because "built on the local copy" and
    "built on what the service returned" are different claims and only one of them is the
    architecture:

    * ``cache`` — we already have the skeleton for these exact format bytes. Keyed by content
      hash, so an edited format is a different skeleton rather than a stale one. This is what
      keeps it at one operation per format version instead of one per report.
    * ``superdocs`` — asked for and returned on this call, then remembered.
    * ``local`` — SuperDocs could not be reached. An inspector who has walked a property still
      gets their report out of the same bytes that were registered. What is not acceptable is
      pretending the round trip happened, so this is reported rather than swallowed.
    """
    from inspection_report.templates import registry

    path = TEMPLATE_DIR / f"{key}.docx"
    if not path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"unknown report format {key!r}. "
            f"Available: {sorted(p.stem for p in TEMPLATE_DIR.glob('*.docx'))}",
        )
    # Computed from the local bytes, so a cache hit costs no call at all.
    sha = registry.content_sha(path.read_bytes())
    provider = _provider()
    cached = db.load_skeleton(conn, sha, provider)
    if cached is not None:
        return cached, "cache"

    client = _client()
    try:
        fmt = registry.ensure_registered(client, TEMPLATE_DIR)[key]
        html, from_service = registry.materialise(client, fmt, session_id=f"format-{sha[:8]}")
    except SuperDocsError as exc:
        _log.warning(
            "template_from_local_copy",
            extra={"format": key, "error": f"{type(exc).__name__}: {str(exc)[:160]}"},
        )
        return _template_html(key), "local"
    finally:
        _release(client)

    if not from_service:
        return html, "local"
    db.save_skeleton(
        conn,
        content_sha=sha,
        provider=provider,
        format_key=key,
        template_name=fmt.name,
        html=html,
    )
    _log.info("template_materialised", extra={"format": key, "sha": sha[:8]})
    return html, "superdocs"


def _load(conn: Any, inspection_id: UUID) -> Inspection:
    inspection = db.load_inspection(conn, inspection_id)
    if inspection is None:
        raise HTTPException(status_code=404, detail="no inspection with that id")
    return inspection


@app.post("/api/inspections/{inspection_id}/prepare")
def prepare_report(
    inspection_id: UUID,
    model_tier: str = "core",
    conn: Any = Depends(get_conn),
) -> Response:
    """Queue the rewrite pass and return immediately.

    This used to do the work inline, which meant the request stayed open for as long as
    SuperDocs took — their own guidance says thirty seconds to several minutes. Any proxy
    with a sixty-second timeout returned 504 to the inspector while the operation was still
    charged, and a database connection stayed pinned throughout.

    Now it enqueues and answers 202 with a job to poll. The work happens in the worker.
    """
    inspection = _load(conn, inspection_id)
    if not inspection.findings:
        raise HTTPException(
            status_code=400,
            detail="this inspection has no findings yet. Record at least one before "
            "preparing the report.",
        )
    try:
        job = jobs.enqueue(
            conn,
            inspection_id=inspection_id,
            kind="prepare",
            payload={"model_tier": model_tier},
        )
    except jobs.JobConflict as exc:
        # 409 rather than a second job: two reviews of one report is a mistake, and the
        # database refuses it so two API processes cannot disagree about that.
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return Response(
        status_code=202,
        media_type="application/json",
        content=json.dumps({"job_id": str(job.id), "state": job.state}),
    )


def _run_prepare(conn: Any, *, inspection: Inspection, template: str, model_tier: str) -> Any:
    """The slow path, lifted out of the request so the worker owns it.

    Everything here was in the route. It is unchanged apart from where it runs, which is the
    point: the fix is that nobody waits on it, not that it does something different.
    """
    from inspection_report.render import pipeline

    client = _client()
    try:
        result = pipeline.prepare(
            inspection,
            template,
            db.photo_data_for(conn, inspection.id),
            client,
            session_id=_session_id(inspection.id),
            known_uploads=db.known_uploads(conn),
            model_tier=model_tier,
        )
    finally:
        _release(client)

    for finding in inspection.findings:
        for photo in finding.photos:
            if photo.remote_url:
                db.remember_upload(conn, sha256=photo.sha256, remote_url=photo.remote_url)

    db.clear_proposals(conn, inspection.id)
    db.record_proposals(
        conn,
        inspection_id=inspection.id,
        rows=[_proposal_row(result, p) for p in result.proposals],
    )
    db.save_inspection(conn, inspection)
    return result


@app.get("/api/jobs/{job_id}")
def get_job(job_id: UUID, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    """Where a queued piece of work got to."""
    job = jobs.get(conn, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="no job with that id")
    return {
        "id": str(job.id),
        "inspection_id": str(job.inspection_id),
        "kind": job.kind,
        "state": str(job.state),
        "result": job.result,
        "error": job.error,
        "attempts": job.attempts,
    }


@app.get("/api/inspections/{inspection_id}/job")
def get_latest_job(inspection_id: UUID, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    """The most recent job for this inspection, so a reload finds its way back to one."""
    job = jobs.latest_for(conn, inspection_id)
    if job is None:
        return {"state": None}
    return {
        "id": str(job.id),
        "state": str(job.state),
        "result": job.result,
        "error": job.error,
    }


@app.get("/api/inspections/{inspection_id}/proposals")
def get_proposals(inspection_id: UUID, conn: Any = Depends(get_conn)) -> dict[str, Any]:
    """Whatever is currently at the gate.

    The interface needs this on load: a review is held open for as long as the person takes,
    and a refreshed browser must find the same queue rather than an empty screen.
    """
    rows = db.load_proposals(conn, inspection_id)
    return {
        "job_id": rows[0]["job_id"] if rows else "",
        "proposals": [
            {
                "change_id": r["change_id"],
                "before": r["old_text"],
                "after": r["new_text"],
                "rail_clean": r["rail_clean"],
                "breaches": r["rail_breaches"],
                "decision": r["decision"],
            }
            for r in rows
        ],
    }


@app.post("/api/inspections/{inspection_id}/decisions")
def submit_decisions(
    inspection_id: UUID, body: dict[str, bool], conn: Any = Depends(get_conn)
) -> dict[str, Any]:
    """Relay the person's decisions. One call per job, so every change is decided together."""
    from inspection_report.phrasing import rail as rail_mod
    from inspection_report.render import pipeline
    from inspection_report.superdocs.models import ChunkDiff

    inspection = _load(conn, inspection_id)
    rows = db.load_proposals(conn, inspection_id)
    if not rows:
        raise HTTPException(
            status_code=400, detail="nothing is awaiting a decision. Prepare the report first."
        )

    result = pipeline.PipelineResult(
        session_id=_session_id(inspection_id),
        document_html="",
        job_id=rows[0]["job_id"],
        proposals=[
            pipeline.Proposal(
                diff=ChunkDiff(
                    change_id=r["change_id"], old_html=r["old_text"], new_html=r["new_text"]
                ),
                verdict=rail_mod.check(r["new_text"]),
            )
            for r in rows
        ],
    )

    client = _client()
    try:
        pipeline.decide(inspection, result, client, approvals=body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SuperDocs: {exc}") from exc
    finally:
        _release(client)

    db.record_proposals(
        conn,
        inspection_id=inspection_id,
        rows=[_proposal_row(result, p) for p in result.proposals],
    )
    db.save_inspection(conn, inspection)
    return _proposals_payload(result)


@app.post("/api/inspections/{inspection_id}/export")
def export_report(inspection_id: UUID, fmt: str = "pdf", conn: Any = Depends(get_conn)) -> Response:
    """Export, then read the finished file back and report what it actually contains."""
    from inspection_report.render import pipeline
    from inspection_report.templates import binding
    from inspection_report.verify import exports as verify_exports

    if fmt not in ("pdf", "docx"):
        raise HTTPException(status_code=400, detail="format must be pdf or docx")
    inspection = _load(conn, inspection_id)
    # The same skeleton the rewrite pass was prepared against — from SuperDocs, cached by the
    # format's content hash — so the export cannot be built on a different shape than the
    # review was.
    template, template_source = _materialised_template(conn, inspection.template_key)

    client = _client()
    try:
        approved = [
            r["new_text"][:60]
            for r in db.load_proposals(conn, inspection_id)
            if r["decision"] == "approved"
        ]
        # Rebuilds the session's document from our own record if the session is gone, so a
        # finished report stays exportable across a restart. The flag says which path it
        # took; it is reported rather than swallowed.
        _with_image_lookup(client, conn)
        # The review ran against a photograph-free document (see `render_report.render`), so
        # the photographs and the approved wording go into the session together, here, before
        # anything is exported.
        export_session = pipeline.finalise_document(
            client, inspection, template, session_id=_session_id(inspection_id)
        )
        export, rebuilt = pipeline.export_recovering_session(
            client,
            inspection,
            template,
            session_id=export_session,
            fmt=fmt,
            filename=_export_name(inspection),
            expected=approved,
            settle_s=pipeline.SETTLE_AFTER_APPROVE_S if _provider() == "live" else 0.0,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"SuperDocs: {exc}") from exc
    finally:
        _release(client)

    card = verify_exports.verify(
        data=export.content,
        fmt=fmt,
        inspection=inspection,
        expect_photos=binding.carries_photos(template, [s.name for s in catalogue.systems()]),
    )
    inspection.stage = ReportStage.EXPORTED
    db.save_inspection(conn, inspection)

    # The verification travels with the file rather than in a separate call, so a client
    # cannot hand someone the document without also having been told what is in it.
    return Response(
        content=export.content,
        media_type=export.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename}"',
            "X-Report-Verified": "pass" if card.passed else "fail",
            # Says how the document reached the export: from the live session, or rebuilt
            # from our own record because the session was gone. A caller should never have
            # to guess which, and the verification below applies either way.
            "X-Report-Source": "rebuilt" if rebuilt else "session",
            # And where the *format* came from: the document SuperDocs returned for the
            # registered format, the cache of a previous such return, or the local copy
            # because the service could not be reached. Built on a local copy is a different
            # claim, and it is made out loud.
            "X-Report-Template": template_source,
            "X-Report-Checks": json.dumps(
                [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in card.checks]
            ),
        },
    )


def _export_name(inspection: Inspection) -> str:
    raw = f"{inspection.property.address_line}-{inspection.inspected_on:%Y-%m-%d}"
    return "".join(c if c.isalnum() else "-" for c in raw.lower()).strip("-")


def _proposal_row(result: Any, proposal: Any) -> dict[str, Any]:
    # No `id` here on purpose: the store derives it from (inspection, change_id) so that
    # recording the same proposal twice updates it instead of duplicating it.
    return {
        "finding_id": None,
        "job_id": result.job_id,
        "change_id": proposal.diff.change_id,
        "old_text": _strip(proposal.diff.old_html),
        "new_text": _strip(proposal.diff.new_html),
        "rail_clean": proposal.verdict.clean,
        "rail_breaches": [
            {"matched": b.matched, "category": b.category, "why": b.why, "suggest": b.suggest}
            for b in proposal.verdict.breaches
        ],
        "decision": ("approved" if proposal.approved else "rejected")
        if proposal.decided
        else "pending",
        "decided_at": None,
    }


def _proposals_payload(result: Any) -> dict[str, Any]:
    return {
        "session_id": result.session_id,
        "job_id": result.job_id,
        "photos_uploaded": result.photos_uploaded,
        "photos_reused": result.photos_reused,
        "ops_charged": result.ops_charged,
        "ops_remaining": result.ops_remaining,
        "provider": _provider(),
        "proposals": [
            {
                "change_id": p.diff.change_id,
                "before": _strip(p.diff.old_html),
                "after": _strip(p.diff.new_html),
                "rail_clean": p.verdict.clean,
                "rail_summary": p.verdict.summary(),
                "approved": p.approved,
                "decided": p.decided,
                "breaches": [
                    {
                        "matched": b.matched,
                        "category": b.category,
                        "why": b.why,
                        "suggest": b.suggest,
                    }
                    for b in p.verdict.breaches
                ],
            }
            for p in result.proposals
        ],
    }


def _strip(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()
