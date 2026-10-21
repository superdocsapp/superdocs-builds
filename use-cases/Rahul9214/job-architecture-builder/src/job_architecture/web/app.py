"""FastAPI application for the reviewer workspace."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from job_architecture.fixtures import PROJECT_ROOT
from job_architecture.web.errors import ApiError
from job_architecture.web.service import WorkspaceService
from job_architecture.web.store import WorkspaceStore


class LevelChangeBody(BaseModel):
    level_id: str | None = None
    dimension: str | None = None
    value: str | None = None
    changes: dict[str, str] | None = None


class DecisionItem(BaseModel):
    plan_id: str
    approved: bool


class DecisionsBody(BaseModel):
    items: list[DecisionItem] = Field(default_factory=list)


class ExportBody(BaseModel):
    kind: str
    profile_id: str | None = None


def create_app(service: WorkspaceService | None = None) -> FastAPI:
    workspace = service or WorkspaceService(WorkspaceStore())
    app = FastAPI(
        title="Job Architecture Reviewer",
        version="0.1.0",
        description="Reviewer-facing API over the existing job-architecture domain services.",
    )
    app.state.service = workspace
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "code": exc.code, "message": exc.message},
        )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "service": "job-architecture-reviewer"}

    @app.get("/api/corpora")
    def corpora() -> dict[str, Any]:
        return {"corpora": workspace.list_corpora()}

    @app.get("/api/corpora/{corpus_id}")
    def corpus(corpus_id: str) -> dict[str, Any]:
        return workspace.get_corpus(corpus_id)

    @app.post("/api/corpora/{corpus_id}/analyze")
    def analyze(corpus_id: str) -> dict[str, Any]:
        return workspace.analyze(corpus_id)

    @app.get("/api/architecture/{corpus_id}")
    def architecture(corpus_id: str) -> dict[str, Any]:
        return workspace.architecture(corpus_id)

    @app.get("/api/architecture/{corpus_id}/roles")
    def roles(corpus_id: str) -> dict[str, Any]:
        return {"roles": workspace.roles(corpus_id)}

    @app.get("/api/architecture/{corpus_id}/roles/{role_id}")
    def role(corpus_id: str, role_id: str) -> dict[str, Any]:
        return workspace.role(corpus_id, role_id)

    @app.get("/api/exceptions/{corpus_id}")
    def exceptions(corpus_id: str) -> dict[str, Any]:
        return workspace.exceptions(corpus_id)

    @app.get("/api/framework/{corpus_id}")
    def framework(corpus_id: str) -> dict[str, Any]:
        return workspace.framework(corpus_id)

    @app.get("/api/profiles/{corpus_id}")
    def profiles(corpus_id: str) -> dict[str, Any]:
        return workspace.profiles(corpus_id)

    @app.get("/api/profiles/{corpus_id}/{profile_id}")
    def profile(corpus_id: str, profile_id: str) -> dict[str, Any]:
        return workspace.profile(corpus_id, profile_id)

    @app.post("/api/impact/{corpus_id}/level-change")
    def impact(corpus_id: str, body: LevelChangeBody) -> dict[str, Any]:
        return workspace.impact(corpus_id, body.model_dump())

    @app.post("/api/updates/{corpus_id}/plan")
    def plan(corpus_id: str, body: LevelChangeBody) -> dict[str, Any]:
        return workspace.plan(corpus_id, body.model_dump())

    @app.get("/api/review/{corpus_id}")
    def review(corpus_id: str) -> dict[str, Any]:
        return workspace.review(corpus_id)

    @app.post("/api/review/{corpus_id}/decisions")
    def decisions(corpus_id: str, body: DecisionsBody) -> dict[str, Any]:
        return workspace.submit_decisions(corpus_id, [item.model_dump() for item in body.items])

    @app.post("/api/review/{corpus_id}/apply")
    def apply_review(corpus_id: str) -> dict[str, Any]:
        return workspace.apply_review(corpus_id)

    @app.get("/api/superdocs/status")
    def superdocs_status() -> dict[str, Any]:
        return workspace.superdocs_status()

    @app.post("/api/export/{corpus_id}")
    def export(corpus_id: str, body: ExportBody) -> dict[str, Any]:
        return workspace.export_local(corpus_id, body.kind, body.profile_id)

    @app.get("/api/export/{corpus_id}/download/{filename}")
    def download_export(corpus_id: str, filename: str) -> FileResponse:
        path = workspace.export_file(corpus_id, filename)
        return FileResponse(path, filename=path.name, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    dist = PROJECT_ROOT / "web" / "dist"
    if dist.is_dir():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend_assets")

        @app.get("/")
        def spa_index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str) -> FileResponse:
            if full_path.startswith("api/"):
                raise ApiError(404, "not_found", f"Unknown API route {full_path}")
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
