"""FastAPI Unified Sidecar Hub — Mounts modular APIRouters for Build A, B, and C.

Run:
    cd build-a/sidecar
    uvicorn server:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Dynamic workspace path resolution for all builds
_base_dir = Path(__file__).resolve().parent.parent.parent
_build_a_sidecar = _base_dir / "build-a" / "sidecar"
_build_b_sidecar = _base_dir / "build-b" / "sidecar"
_build_c_sidecar = _base_dir / "build-c" / "sidecar"

for p in [_build_a_sidecar, _build_b_sidecar, _build_c_sidecar]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

# Import modular routers
from build_a.router import router as build_a_router
from build_b.router import router as build_b_router
from build_c.router import router as build_c_router

_root_env = _base_dir / ".env"
if _root_env.exists():
    load_dotenv(dotenv_path=_root_env)
load_dotenv()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SuperDocs Unified Sidecar Hub (Builds A, B & C)",
    description="Aviation FCOM Revision (Build A), FinOps ROI Calculator (Build B), and Study Guide Synthesizer (Build C)",
    version="1.0.0",
)


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc), "type": type(exc).__name__})


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Build A (Aviation)
        "http://localhost:5174",  # Build B (FinOps)
        "http://localhost:5175",  # Build C (Study Guide)
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount modular APIRouters cleanly
app.include_router(build_a_router)
app.include_router(build_b_router)
app.include_router(build_c_router)


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "builds": ["Build A (FCOM)", "Build B (FinOps)", "Build C (Study Guide)"],
    }
