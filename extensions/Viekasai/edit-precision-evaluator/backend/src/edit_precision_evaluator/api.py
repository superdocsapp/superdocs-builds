from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .corpus import load_corpus, validate_corpus


def project_root() -> Path:
    configured = os.getenv("EDIT_PRECISION_PROJECT_ROOT")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3]


def _report_path(root: Path) -> tuple[Path, str]:
    configured = os.getenv("EDIT_PRECISION_REPORT")
    if configured:
        return Path(configured), "configured"
    live = root / "results/live/latest.json"
    if live.is_file():
        return live, "live"
    return root / "results/demo.json", "fixture"


def create_app(root: Path | None = None) -> FastAPI:
    root = (root or project_root()).resolve()
    corpus_path = root / "corpus/cases.jsonl"
    document_root = root / "corpus/documents"

    app = FastAPI(
        title="SuperDocs Edit Precision Evaluator",
        version="0.1.0",
        description="API for labelled edit-precision and collateral-damage results.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict:
        errors = validate_corpus(corpus_path, document_root)
        return {"status": "ok" if not errors else "degraded", "corpus_errors": errors}

    @app.get("/api/corpus")
    def corpus_summary() -> dict:
        cases = load_corpus(corpus_path)
        return {
            "cases": len(cases),
            "by_instruction_type": dict(
                sorted(Counter(case.instruction_type.value for case in cases).items())
            ),
            "by_review_status": dict(
                sorted(Counter(case.review_status.value for case in cases).items())
            ),
            "ambiguous_cases": [case.case_id for case in cases if case.ambiguity_note],
        }

    @app.get("/api/cases")
    def cases() -> list[dict]:
        return [case.model_dump(mode="json") for case in load_corpus(corpus_path)]

    @app.get("/api/report")
    def report() -> dict:
        path, source = _report_path(root)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="No evaluation report is available")
        try:
            payload = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="Evaluation report is invalid") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=500, detail="Evaluation report has an invalid shape")
        payload["data_source"] = source
        return payload

    frontend_dist = root / "frontend/dist"
    if frontend_dist.is_dir():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="dashboard")

    return app


app = create_app()
