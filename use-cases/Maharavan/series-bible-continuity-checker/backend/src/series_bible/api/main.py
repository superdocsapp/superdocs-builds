import time
import hmac
from uuid import uuid4
import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from series_bible.api.routes.core import router
from series_bible.config import get_settings
from series_bible.infrastructure.auth import AuthenticationError, verify_token
from series_bible.infrastructure.database import engine

settings = get_settings()
log = structlog.get_logger()
app = FastAPI(title=settings.app_name, version="1.0.0", docs_url="/api/docs")
app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_credentials=False, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "X-Request-ID", "Authorization"])
app.include_router(router)

@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started = time.perf_counter()
    is_google_login = request.url.path == "/api/v1/auth/google"
    if request.url.path.startswith("/api/v1") and settings.api_auth_token is not None and not is_google_login:
        authorization = request.headers.get("Authorization", "")
        expected = f"Bearer {settings.api_auth_token.get_secret_value()}"
        is_static_token = hmac.compare_digest(authorization, expected)
        is_user_token = False
        if authorization.startswith("Bearer ") and settings.jwt_secret is not None:
            try:
                verify_token(authorization.removeprefix("Bearer "), settings)
                is_user_token = True
            except AuthenticationError:
                pass
        if not is_static_token and not is_user_token:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "UNAUTHORIZED", "message": "Valid bearer token required", "request_id": request_id}},
                headers={"WWW-Authenticate": "Bearer", "X-Request-ID": request_id},
            )
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
