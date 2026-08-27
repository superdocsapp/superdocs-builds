import time
from uuid import uuid4
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from series_bible.api.routes.core import router
from series_bible.config import get_settings
from series_bible.infrastructure.database import engine

settings = get_settings()
log = structlog.get_logger()
app = FastAPI(title=settings.app_name, version="1.0.0", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Request-ID"])
app.include_router(router)

@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("request_failed", request_id=request_id, path=request.url.path)
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "The request could not be completed", "request_id": request_id}})
    response.headers["X-Request-ID"] = request_id
    log.info("request_completed", request_id=request_id, path=request.url.path, status=response.status_code, duration_ms=round((time.perf_counter()-started)*1000, 2))
    return response

@app.get("/health/live")
async def live():
    return {"status": "live"}

@app.get("/health/ready")
async def ready():
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
