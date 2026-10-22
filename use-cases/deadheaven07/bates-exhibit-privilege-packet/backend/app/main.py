import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    audit,
    bates,
    documents,
    exports,
    health,
    packets,
    privilege,
    processing,
    redactions,
    review,
    search,
)
from app.config import get_settings
from app.database import close_db, init_db

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up...")
    settings.ensure_directories()
    await init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutting down...")
    await close_db()
    logger.info("Database closed")


app = FastAPI(
    title="Bates Exhibit & Privilege Packet Builder",
    description=(
        "Legal e-discovery packet builder with Bates stamping, privilege "
        "logging, and redaction workflow"
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(packets.router, prefix="/api/packets", tags=["packets"])
app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(processing.router, prefix="/api/processing", tags=["processing"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(privilege.router, prefix="/api/privilege", tags=["privilege"])
app.include_router(redactions.router, prefix="/api/redactions", tags=["redactions"])
app.include_router(bates.router, prefix="/api/bates", tags=["bates"])
app.include_router(exports.router, prefix="/api/exports", tags=["exports"])
app.include_router(search.router, prefix="/api/search", tags=["search"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])


@app.get("/")
async def root():
    return {
        "name": "Bates Exhibit & Privilege Packet Builder",
        "version": "0.1.0",
        "status": "running",
    }
