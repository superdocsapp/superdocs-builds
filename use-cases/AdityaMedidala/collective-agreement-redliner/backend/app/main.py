import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import negotiations, rounds, tracker

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(
    title="collective-agreement-redliner",
    description="SuperDocs Round 2, Task 2 — redlines a CBA against each side's position.",
)

app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"]
)

app.include_router(negotiations.router)
app.include_router(rounds.router)
app.include_router(tracker.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
