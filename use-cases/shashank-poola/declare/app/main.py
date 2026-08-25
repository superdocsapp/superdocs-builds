from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routes.declare import router as declare_router
from routes.errors import failure
from routes.superdocs import router as superdocs_router

MAX_BODY_BYTES = 32 * 1024 * 1024

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "https://declare.shashank.ink"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(declare_router)
app.include_router(superdocs_router)


def validation_error_code(path: str) -> str:
    if path.endswith("/analyze"):
        return "INVALID_ANALYZE_REQUEST_OR_GLM_RESPONSE"
    if path.endswith("/statements"):
        return "INVALID_STATEMENTS_REQUEST"
    return "INVALID_SUPERDOCS_REQUEST"


@app.middleware("http")
async def payload_limit(request: Request, call_next):
    length = request.headers.get("content-length")
    if length and int(length) > MAX_BODY_BYTES:
        return failure(413, "PAYLOAD_TOO_LARGE", message="The uploaded manuscript is too large. Please use a file smaller than 20 MB.")
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def validation_exception(request: Request, exc: RequestValidationError):
    return failure(400, validation_error_code(request.url.path), [{"type": "VALIDATION_ERROR", "message": error["msg"]} for error in exc.errors()])


@app.get("/health")
async def health():
    return {"success": True, "service": "declare"}
