"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.config import get_settings
from app.logging import RequestContextMiddleware, configure_logging
from app.services.queue import close_job_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(get_settings().log_level)
    yield
    # Clean up the shared Redis pool on shutdown.
    await close_job_queue()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tenant Doc Gateway",
        version="0.1.0",
        description=(
            "Multi-tenant reference service wrapping the SuperDocs "
            "upload/chat/approve/export contract."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router)
    app.state.settings = settings
    return app


app = create_app()
