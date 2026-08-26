"""Thin FastAPI routes over ``generator.service`` — machine driver, optional UI later."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from generator.api.runs import RUNS
from generator.service import (
    divergence_report,
    ledger_snapshot,
    list_verticals,
    narrative_export_path,
    run_verticals,
)
from generator.startup_checks import require_runtime_config


def _load_dotenv() -> None:
    """Load KEY=VALUE from project ``.env`` without overriding existing env."""
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _load_dotenv()
    # Unit tests set PITCH_SKIP_API_KEY_CHECK=1 — they never call SuperDocs.
    require_runtime_config(
        require_api_key=os.environ.get("PITCH_SKIP_API_KEY_CHECK") != "1"
    )
    yield


app = FastAPI(
    title="ClarityDocs pitch-script generator",
    description=(
        "Machine driver for speaking-script narratives. "
        "Not a slide deck. POST /generate returns a run id immediately; poll GET /runs/{id}."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def create_app() -> FastAPI:
    return app


@app.get("/verticals")
def get_verticals() -> dict:
    return list_verticals()


@app.post("/generate")
def post_generate(
    background_tasks: BackgroundTasks,
    vertical: str = Query(..., description="Vertical code, or 'all'."),
    force: bool = Query(False),
) -> JSONResponse:
    """Queue generation. Does not wait on SuperDocs — poll ``GET /runs/{run_id}``."""
    known = list_verticals()["verticals"]
    if vertical != "all" and vertical not in known:
        raise HTTPException(
            status_code=404,
            detail=f"unknown vertical {vertical!r}; known: {known} (or 'all')",
        )
    run_id = RUNS.create(vertical, force)
    background_tasks.add_task(_execute_run, run_id)
    return JSONResponse(
        status_code=202,
        content={
            "run_id": run_id,
            "status": "queued",
            "poll": f"/runs/{run_id}",
            "vertical": vertical,
        },
    )


async def _execute_run(run_id: str) -> None:
    rec = RUNS.get(run_id)
    if rec is None:
        return
    RUNS.mark(run_id, "running")
    try:
        result = await run_verticals(rec["vertical"], force=bool(rec["force"]))
        RUNS.mark(run_id, "done", result=result)
    except Exception as exc:  # noqa: BLE001 — surface any generate failure on poll
        RUNS.mark(run_id, "error", error=str(exc))


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    rec = RUNS.get(run_id)
    if rec is None:
        raise HTTPException(status_code=404, detail=f"unknown run_id {run_id!r}")
    return rec


@app.get("/narratives/{vertical_code}")
def get_narrative(
    vertical_code: str,
    fmt: str = Query("markdown", alias="format"),
) -> FileResponse:
    try:
        path = narrative_export_path(vertical_code, fmt)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    media = (
        "text/markdown; charset=utf-8"
        if path.suffix.lower() in {".md", ".markdown"}
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media, filename=path.name)


@app.get("/divergence")
def get_divergence() -> dict:
    return divergence_report()


@app.get("/ledger")
def get_ledger() -> dict:
    return ledger_snapshot()
