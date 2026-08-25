"""
@file: backend/main.py
@description: FastAPI application entry point. Wires the three routers, configures CORS
    for the frontend, sets up logging that never emits credentials, and ensures the
    database schema exists on startup.
@flow: lifespan startup -> init_db() creates the pgvector extension (and tables when
    running without Alembic) -> routers mounted -> requests served -> shutdown disposes
    the engine so connections close cleanly.
@dependencies:
    - fastapi / uvicorn: HTTP server
    - backend.api.*: the route modules
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import approve, health, runs
from backend.config import settings
from backend.db.database import dispose_engine, init_db

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # AUTO_CREATE_TABLES is for the demo path and tests. Alembic owns the schema in any
    # real deployment; creating tables implicitly there would mask a missed migration.
    auto_create = os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true"
    try:
        await init_db(create_all=auto_create)
    except Exception as exc:  # noqa: BLE001
        # Start anyway so /health/ready can report the failure. Refusing to boot would
        # leave an operator with no endpoint to diagnose against.
        logger.error("Database initialisation failed: %s", exc)
    logger.info("VocDigest API ready (SuperDocs base: %s)", settings.superdocs_base_url)
    yield
    await dispose_engine()


app = FastAPI(
    title="VocDigest",
    description="Voice-of-Customer digest generation with a human approval gate.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(runs.router)
app.include_router(approve.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "vocdigest", "docs": "/docs", "health": "/health"}
