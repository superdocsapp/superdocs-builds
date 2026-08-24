from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from docrelay import __version__
from docrelay.core.config import Settings
from docrelay.persistence.database import Database

router = APIRouter(tags=["system"])


class LiveResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["docrelay-api"] = "docrelay-api"
    version: str = __version__


class DependencyStatus(BaseModel):
    status: Literal["ready", "unavailable"]
    detail: str | None = None


class ReadyResponse(BaseModel):
    status: Literal["ready", "unavailable"]
    dependencies: dict[str, DependencyStatus] = Field(default_factory=dict)


@router.get("/health/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse()


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    database: Database = request.app.state.database
    settings: Settings = request.app.state.settings
    try:
        await database.ping(settings.readiness_timeout_seconds)
    except (TimeoutError, OSError, SQLAlchemyError):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadyResponse(
            status="unavailable",
            dependencies={
                "postgresql": DependencyStatus(
                    status="unavailable",
                    detail="required database check failed",
                )
            },
        )
    return ReadyResponse(
        status="ready",
        dependencies={"postgresql": DependencyStatus(status="ready")},
    )
