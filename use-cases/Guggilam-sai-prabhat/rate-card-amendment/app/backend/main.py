"""FastAPI application entry point for the Rate-Card Amendment Propagation
backend. Run with: `uv run uvicorn app.backend.main:app --reload`.
"""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()  # populates SUPERDOCS_API_KEY (and any other vars) from .env if present

from app.backend.routes import analysis, intake, results, review

app = FastAPI(
    title="Rate-Card Amendment Propagation",
    description=(
        "Intake wholesale telecom contracts + a new rate card, run the "
        "deterministic eligibility pipeline, propose scoped edits through "
        "SuperDocs under human review, and export the amended contract, "
        "amendment letter, and control report."
    ),
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(intake.router, tags=["intake"])
app.include_router(analysis.router, tags=["analysis"])
app.include_router(review.router, tags=["review"])
app.include_router(results.router, tags=["results"])


@app.get("/health")
async def health():
    return {"status": "healthy"}
