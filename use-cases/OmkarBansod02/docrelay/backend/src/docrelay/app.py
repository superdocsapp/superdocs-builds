import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.transport_security import TransportSecuritySettings

from docrelay import __version__
from docrelay.api.google import GoogleErrorBody, GoogleErrorResponse, clear_oauth_callback_cookies
from docrelay.api.google import router as google_router
from docrelay.api.health import router as health_router
from docrelay.api.middleware import RequestIdMiddleware
from docrelay.api.runs import router as runs_router
from docrelay.api.watch import router as watch_router
from docrelay.core.config import Settings, get_settings
from docrelay.core.logging import configure_logging
from docrelay.integrations.google.errors import GoogleErrorCode, GoogleIntegrationError
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.superdocs.client import (
    SuperDocsError,
    SuperDocsInvalidResponse,
    SuperDocsRequestError,
)
from docrelay.integrations.superdocs.runtime import SuperDocsRuntime
from docrelay.mcp import create_mcp_server
from docrelay.persistence.database import Database
from docrelay.services.artifacts import ArtifactStore, FilesystemArtifactStore
from docrelay.services.machine import MachineOperations
from docrelay.services.superdocs_workflow import (
    ExportNotReady,
    IncompleteDecisionSet,
    ReviewOperationInvalid,
    ReviewPayloadInvalid,
    RunNotFound,
    SelectedBaselineChanged,
    SourceNotFound,
    SuperDocsNotConfigured,
    SuperDocsWorkflowError,
)
from docrelay.services.watch import WatchError, WatchNotFound
from docrelay.services.writeback import WriteBackError


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    google_runtime: GoogleRuntime | None = None,
    superdocs_runtime: SuperDocsRuntime | None = None,
    artifact_store: ArtifactStore | None = None,
    machine_operations: MachineOperations | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    app_database = database or Database(app_settings.database_url)
    app_google_runtime = google_runtime or GoogleRuntime.from_settings(app_settings)
    app_superdocs_runtime = superdocs_runtime or SuperDocsRuntime.from_settings(app_settings)
    app_artifact_store = artifact_store or FilesystemArtifactStore(
        app_settings.docrelay_artifact_dir
    )
    app_machine_operations = machine_operations or MachineOperations(
        settings=app_settings,
        database=app_database,
        artifacts=app_artifact_store,
        google_runtime=app_google_runtime,
        superdocs_runtime=app_superdocs_runtime,
    )
    mcp_server = create_mcp_server(app_machine_operations)
    mcp_app = mcp_server.streamable_http_app(
        streamable_http_path="/",
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=app_settings.mcp_allowed_hosts,
            allowed_origins=app_settings.mcp_allowed_origins,
        ),
    )
    configure_logging(app_settings.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async with mcp_server.session_manager.run():
            yield
        if app_google_runtime is not None:
            await app_google_runtime.close()
        if app_superdocs_runtime is not None:
            await app_superdocs_runtime.close()
        await app_database.dispose()

    app = FastAPI(
        title="DocRelay API",
        summary="Safety-first control plane for cloud-document write-back",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if app_settings.app_env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if app_settings.app_env != "production" else None,
    )
    app.state.settings = app_settings
    app.state.database = app_database
    app.state.google_runtime = app_google_runtime
    app.state.superdocs_runtime = app_superdocs_runtime
    app.state.artifact_store = app_artifact_store
    app.state.machine_operations = app_machine_operations
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health_router)
    app.include_router(google_router)
    app.include_router(runs_router)
    app.include_router(watch_router)
    app.mount("/mcp", mcp_app, name="mcp")

    @app.exception_handler(GoogleIntegrationError)
    async def handle_google_error(request: Request, exc: GoogleIntegrationError) -> Response:
        status_by_code = {
            GoogleErrorCode.OAUTH_NOT_CONFIGURED: 503,
            GoogleErrorCode.INVALID_OAUTH_STATE: 400,
            GoogleErrorCode.OAUTH_ACCESS_DENIED: 403,
            GoogleErrorCode.REAUTH_REQUIRED: 401,
            GoogleErrorCode.WATCH_AUTHORIZATION_REQUIRED: 403,
            GoogleErrorCode.PERMISSION_DENIED: 403,
            GoogleErrorCode.CONNECTION_NOT_FOUND: 404,
            GoogleErrorCode.FILE_NOT_FOUND: 404,
            GoogleErrorCode.UNSUPPORTED_SOURCE_TYPE: 422,
            GoogleErrorCode.SOURCE_TRASHED: 409,
            GoogleErrorCode.SOURCE_CHANGED_DURING_CAPTURE: 409,
            GoogleErrorCode.RATE_LIMITED: 429,
            GoogleErrorCode.UNAVAILABLE: 503,
            GoogleErrorCode.INVALID_RESPONSE: 502,
        }
        payload = GoogleErrorResponse(
            error=GoogleErrorBody(
                code=exc.code,
                message=exc.safe_message,
                retryable=exc.retryable,
                details=exc.safe_details,
            )
        )
        response = Response(
            content=payload.model_dump_json(),
            status_code=status_by_code[exc.code],
            media_type="application/json",
        )
        if request.url.path == "/api/v1/google/oauth/callback":
            clear_oauth_callback_cookies(response, app_settings)
        return response

    @app.exception_handler(SuperDocsWorkflowError)
    async def handle_superdocs_workflow_error(_: Request, exc: SuperDocsWorkflowError) -> Response:
        if isinstance(exc, (RunNotFound, SourceNotFound)):
            status_code = 404
        elif isinstance(exc, SuperDocsNotConfigured):
            status_code = 503
        elif isinstance(
            exc,
            (
                IncompleteDecisionSet,
                ReviewOperationInvalid,
                ReviewPayloadInvalid,
                SelectedBaselineChanged,
                ExportNotReady,
            ),
        ):
            status_code = 409
        else:
            status_code = 422
        return Response(
            content=json.dumps(
                {"error": {"code": exc.code, "message": exc.safe_message}},
                separators=(",", ":"),
            ),
            status_code=status_code,
            media_type="application/json",
        )

    @app.exception_handler(SuperDocsError)
    async def handle_superdocs_error(_: Request, exc: SuperDocsError) -> Response:
        if isinstance(exc, SuperDocsInvalidResponse):
            status_code = 502
            code = "SUPERDOCS_INVALID_RESPONSE"
            message = str(exc)
        elif isinstance(exc, SuperDocsRequestError):
            status_code = 429 if exc.status_code == 429 else 503
            code = "SUPERDOCS_UNAVAILABLE"
            message = exc.safe_message
        else:
            status_code = 502
            code = "SUPERDOCS_ERROR"
            message = "SuperDocs integration failed"
        return Response(
            content=json.dumps(
                {"error": {"code": code, "message": message}}, separators=(",", ":")
            ),
            status_code=status_code,
            media_type="application/json",
        )

    @app.exception_handler(WriteBackError)
    async def handle_write_back_error(_: Request, exc: WriteBackError) -> Response:
        return Response(
            content=json.dumps(
                {"error": {"code": exc.code, "message": exc.safe_message}},
                separators=(",", ":"),
            ),
            status_code=409,
            media_type="application/json",
        )

    @app.exception_handler(WatchError)
    async def handle_watch_error(_: Request, exc: WatchError) -> Response:
        return Response(
            content=json.dumps(
                {"error": {"code": exc.code, "message": exc.safe_message}},
                separators=(",", ":"),
            ),
            status_code=404 if isinstance(exc, WatchNotFound) else 409,
            media_type="application/json",
        )

    return app
