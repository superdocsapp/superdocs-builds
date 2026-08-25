from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import time

from backend.config import settings
from backend.logging_config import configure_logging, get_logger
from backend.database import check_db_connection, async_session_maker
from backend.api.v1 import workspaces, documents, reviews, exports
from backend.api.v1 import runs as runs_router_module
from backend.api.v1.stream import router as stream_router
from backend.api.v1.quality_gate import router as quality_gate_router
from backend.api.v1.knowledge import router as knowledge_router
from backend.api.v1.audit import router as audit_router
from backend.api.v1.evidence import router as evidence_router
from backend.api.v1.auth import router as auth_router

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("application_starting", version="0.1.0")

    # Check database connection
    db_ok = await check_db_connection()
    if not db_ok:
        logger.error("startup_failed", reason="database_connection_failed")
        raise RuntimeError("Cannot connect to database")

    # Register workflows
    try:
        from backend.modules.tariff.workflow import register_tariff_workflow
        register_tariff_workflow()
        logger.info("workflows_registered")
    except Exception as e:
        logger.error("workflow_registration_failed", error=str(e))
        raise

    # Register screenplay workflow
    try:
        from backend.modules.screenplay.workflow import register_screenplay_workflow
        register_screenplay_workflow()
        logger.info("screenplay_workflow_registered")
    except Exception as e:
        logger.error("screenplay_workflow_registration_failed", error=str(e))
        raise

    # Initialize task manager (creates its own sessions as needed)
    try:
        from backend.core.workflow.task_manager import init_task_manager
        init_task_manager()
        logger.info("task_manager_initialized")
    except Exception as e:
        logger.error("task_manager_init_failed", error=str(e))
        raise

    # Resubmit any runs that were running/queued when the server last stopped
    try:
        from backend.core.workflow.task_manager import get_task_manager
        from backend.repositories.workflow import WorkflowRunRepository
        async with async_session_maker() as session:
            run_repo = WorkflowRunRepository(session)
            runs = await run_repo.list_by_status(["running", "queued"])
        if runs:
            logger.info("resubmitting_interrupted_runs", count=len(runs))
        # Resubmit handled lazily — runs will be retried when their status is polled
    except Exception as e:
        logger.warning("run_resubmit_check_failed", error=str(e))

    logger.info("application_ready")
    yield
    # Shutdown
    logger.info("application_shutting_down")


app = FastAPI(
    title="DocIntel Platform API",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers

# Auth router (public endpoints - no authentication required)
try:
    app.include_router(auth_router, prefix="/api/v1")
    logger.info("auth_router_registered", routes=len(auth_router.routes))
except Exception as e:
    logger.error("auth_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(workspaces.router, prefix="/api/v1")
    logger.info("workspace_router_registered", routes=len(workspaces.router.routes))
except Exception as e:
    logger.error("workspace_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(documents.router, prefix="/api/v1")
    logger.info("document_router_registered", routes=len(documents.router.routes))
except Exception as e:
    logger.error("document_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(runs_router_module.router, prefix="/api/v1")
    logger.info("runs_router_registered", routes=len(runs_router_module.router.routes))
except Exception as e:
    logger.error("runs_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(reviews.router, prefix="/api/v1")
    logger.info("review_router_registered", routes=len(reviews.router.routes))
except Exception as e:
    logger.error("review_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(exports.router, prefix="/api/v1")
    logger.info("export_router_registered", routes=len(exports.router.routes))
except Exception as e:
    logger.error("export_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(stream_router, prefix="/api/v1")
    logger.info("stream_router_registered", routes=len(stream_router.routes))
except Exception as e:
    logger.error("stream_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(quality_gate_router, prefix="/api/v1")
    logger.info("quality_gate_router_registered", routes=len(quality_gate_router.routes))
except Exception as e:
    logger.error("quality_gate_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(knowledge_router, prefix="/api/v1")
    logger.info("knowledge_router_registered", routes=len(knowledge_router.routes))
except Exception as e:
    logger.error("knowledge_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(audit_router, prefix="/api/v1")
    logger.info("audit_router_registered", routes=len(audit_router.routes))
except Exception as e:
    logger.error("audit_router_registration_failed", error=str(e))
    raise

try:
    app.include_router(evidence_router, prefix="/api/v1")
    logger.info("evidence_router_registered", routes=len(evidence_router.routes))
except Exception as e:
    logger.error("evidence_router_registration_failed", error=str(e))
    raise

try:
    from backend.api.v1.screenplay import router as screenplay_router
    app.include_router(screenplay_router, prefix="/api/v1")
    logger.info("screenplay_router_registered", routes=len(screenplay_router.routes))
except Exception as e:
    logger.error("screenplay_router_registration_failed", error=str(e))
    raise

try:
    from backend.api.v1.lineage import router as lineage_router, replay_router
    app.include_router(lineage_router, prefix="/api/v1")
    app.include_router(replay_router, prefix="/api/v1")
    logger.info("lineage_router_registered", routes=len(lineage_router.routes))
    logger.info("replay_router_registered", routes=len(replay_router.routes))
except Exception as e:
    logger.error("lineage_router_registration_failed", error=str(e))
    raise


@app.middleware("http")
async def add_request_id_and_logging(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id

    start_time = time.time()

    logger.info(
        "request_started",
        request_id=request_id,
        method=request.method,
        path=request.url.path
    )

    response = await call_next(request)

    duration_ms = int((time.time() - start_time) * 1000)

    logger.info(
        "request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=duration_ms
    )

    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health_check():
    db_ok = await check_db_connection()
    return {
        "status": "healthy" if db_ok else "unhealthy",
        "database": "ok" if db_ok else "error",
        "version": "0.1.0"
    }


@app.get("/")
async def root():
    return {
        "service": "DocIntel Platform API",
        "version": "0.1.0",
        "docs": "/docs"
    }
