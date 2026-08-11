from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from contextlib import asynccontextmanager
import logging

from backend.app.config import settings
from backend.app.database import get_db, Base, engine
from backend.app.schemas import HealthCheckResponse
from backend.app.api.v1.documents import router as documents_router
from backend.app.api.v1.questions import router as questions_router
from backend.app.api.v1.dossiers import router as dossiers_router
from backend.app.api.v1.accessibility import router as accessibility_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager. Runs startup database setup (creating tables
    and registering pgvector extension) and handles shutdown cleanup.
    """
    logger.info("Starting up backend API server...")
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully (tables created).")
    except Exception as e:
        logger.error(f"Failed to initialize database on startup: {e}")
    yield
    logger.info("Shutting down backend API server...")

app = FastAPI(
    title="Diligence Q&A Dossier Builder API",
    description="Backend API for the Diligence Q&A Dossier Builder",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(documents_router, prefix="/api/v1")
app.include_router(questions_router, prefix="/api/v1")
app.include_router(dossiers_router, prefix="/api/v1")
app.include_router(accessibility_router, prefix="/api/v1")

@app.get("/api/v1/health", response_model=HealthCheckResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Health check endpoint to verify API and database connection status.
    """
    database_status = "unhealthy"
    try:
        # Perform a simple check using select 1
        result = await db.execute(text("SELECT 1"))
        if result.scalar() == 1:
            database_status = "healthy"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        database_status = f"unhealthy: {str(e)}"

    return HealthCheckResponse(
        status="healthy",
        database=database_status,
        environment=settings.APP_ENV
    )

@app.get("/")
async def root():
    return {"message": "Welcome to Diligence Q&A Dossier Builder API. Health check available at /api/v1/health"}
