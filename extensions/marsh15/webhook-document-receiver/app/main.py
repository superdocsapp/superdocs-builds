import hmac
import json
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.persistence import DeliveryCollisionError, DeliveryStore, ReviewDecision
from app.routes import Route, load_routes
from app.security import SignatureError, VerifiedWebhook, verify_webhook


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    pool = ConnectionPool(
        settings.database_url,
        min_size=1,
        max_size=settings.database_pool_max_size,
        open=False,
    )
    pool.open(wait=True)
    app.state.pool = pool
    app.state.deliveries = DeliveryStore(pool)
    app.state.routes = load_routes(settings.routes_path)
    yield
    pool.close()


app = FastAPI(title="Webhook Document Receiver", version="2.0.0", lifespan=lifespan)


class DecisionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_id: str = Field(min_length=1, max_length=128)
    approved: bool
    reason: str | None = Field(default=None, max_length=1000)


class DecisionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[DecisionItem] = Field(min_length=1, max_length=100)

    @field_validator("decisions")
    @classmethod
    def unique_change_ids(cls, decisions: list[DecisionItem]) -> list[DecisionItem]:
        ids = [decision.change_id for decision in decisions]
        if len(ids) != len(set(ids)):
            raise ValueError("A change may be decided only once per request")
        return decisions


def require_management(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    if len(authorization) > 1024:
        raise HTTPException(status_code=401, detail="Invalid management credentials")
    scheme, separator, supplied = authorization.partition(" ")
    expected = get_settings().management_token.get_secret_value()
    if (
        not separator
        or scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied, expected)
    ):
        raise HTTPException(status_code=401, detail="Invalid management credentials")
    return get_settings().management_actor_id


async def read_webhook_body(request: Request) -> bytes:
    settings = get_settings()
    if request.headers.get("content-type", "").split(";", 1)[0].strip() != "application/json":
        raise HTTPException(status_code=415, detail="Content-Type must be application/json")
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_body_bytes:
                raise HTTPException(status_code=413, detail="Webhook body is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length is malformed") from exc
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > settings.max_body_bytes:
            raise HTTPException(status_code=413, detail="Webhook body is too large")
        body.extend(chunk)
    return bytes(body)


def parse_payload(body: bytes) -> dict[str, object]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail="Webhook body must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Webhook body must be a JSON object")
    settings = get_settings()
    stack: list[tuple[object, int]] = [(payload, 1)]
    nodes = 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > settings.max_json_nodes:
            raise HTTPException(status_code=422, detail="Webhook JSON is too complex")
        if isinstance(value, dict):
            if depth > settings.max_json_depth:
                raise HTTPException(status_code=422, detail="Webhook JSON is nested too deeply")
            stack.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            if depth > settings.max_json_depth:
                raise HTTPException(status_code=422, detail="Webhook JSON is nested too deeply")
            stack.extend((child, depth + 1) for child in value)
    return payload


async def persist_event(
    *,
    request: Request,
    verified: VerifiedWebhook,
    event_type: str,
    payload: dict[str, object],
    route: Route,
) -> dict[str, object]:
    allowed_fields = set(route.payload_fields)
    input_data = {key: value for key, value in payload.items() if key in allowed_fields}
    try:
        accepted = await run_in_threadpool(
            request.app.state.deliveries.accept,
            verified=verified,
            event_type=event_type,
            route_id=route.id,
            route_config_version=request.app.state.routes.version,
            input_data=input_data,
            route_config=route.model_dump(mode="json"),
        )
    except DeliveryCollisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "delivery_id": str(accepted.delivery_id),
        "job_id": str(accepted.job_id),
        "status": accepted.status,
        "duplicate": accepted.duplicate,
    }


@app.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "ok"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/":
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
        )
    elif request.url.path not in {"/docs", "/redoc"}:
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def receiver_overview() -> str:
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Webhook Document Receiver</title><style>
body{margin:0;background:#f5f1e8;color:#22251f;font:16px/1.5 system-ui,sans-serif}
main{max-width:880px;margin:0 auto;padding:64px 24px}p{color:#5b6056}h1{font:600 48px/1.05 Georgia,serif;max-width:700px}
.flow{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin:40px 0}.step{border-top:3px solid #42614b;padding:14px 8px;background:#fffdf7}.step b{display:block;font-size:12px;letter-spacing:.08em;text-transform:uppercase}
code{background:#e8e3d8;padding:3px 6px}@media(max-width:700px){.flow{grid-template-columns:1fr}h1{font-size:36px}}
</style></head><body><main><p>SUPERDOCS EXTENSION · PLATFORM</p><h1>Authenticated events become reviewed documents.</h1>
<p>Raw-body verification, replay protection, durable PostgreSQL work, item-level approval, and bounded export.</p>
<div class="flow"><div class="step"><b>01 Verify</b>HMAC bytes</div><div class="step"><b>02 Persist</b>Delivery + job</div><div class="step"><b>03 Process</b>Generate or edit</div><div class="step"><b>04 Review</b>Approve/reject</div><div class="step"><b>05 Export</b>Digest artifact</div></div>
<p>Health: <code>GET /health/ready</code> · API: <code>/docs</code></p></main></body></html>"""


@app.get("/health/ready")
def health_ready(request: Request) -> dict[str, str]:
    with request.app.state.pool.connection() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ready"}


@app.post("/v1/webhooks/generic-hmac", status_code=status.HTTP_202_ACCEPTED)
async def receive_generic_hmac(request: Request) -> dict[str, object]:
    settings = get_settings()
    body = await read_webhook_body(request)

    try:
        verified = verify_webhook(
            body=body,
            headers=request.headers,
            secret=settings.webhook_secret.get_secret_value(),
            provider="generic-hmac",
            signature_header="x-webhook-signature",
            event_id_header="x-webhook-id",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=settings.signature_tolerance_seconds,
        )
    except SignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    payload = parse_payload(body)
    event_type = payload.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise HTTPException(status_code=422, detail="Webhook payload requires a string type")
    route = request.app.state.routes.resolve(provider="generic-hmac", event_type=event_type)
    if route is None:
        raise HTTPException(status_code=404, detail="No enabled route matches this event")

    return await persist_event(
        request=request,
        verified=verified,
        event_type=event_type,
        payload=payload,
        route=route,
    )


@app.post("/v1/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def receive_github(request: Request) -> dict[str, object]:
    settings = get_settings()
    body = await read_webhook_body(request)
    try:
        verified = verify_webhook(
            body=body,
            headers=request.headers,
            secret=settings.github_webhook_secret.get_secret_value(),
            provider="github",
            signature_header="x-hub-signature-256",
            event_id_header="x-github-delivery",
            timestamp_header="x-webhook-timestamp",
            tolerance_seconds=settings.signature_tolerance_seconds,
        )
    except SignatureError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    payload = parse_payload(body)
    github_event = request.headers.get("x-github-event")
    if not github_event:
        raise HTTPException(status_code=422, detail="Missing required header: x-github-event")
    if github_event == "ping":
        return {"status": "pong", "delivery_id": verified.event_id}
    action = payload.get("action")
    event_type = f"{github_event}.{action}" if isinstance(action, str) and action else github_event
    route = request.app.state.routes.resolve(provider="github", event_type=event_type)
    if route is None:
        raise HTTPException(status_code=404, detail="No enabled route matches this event")
    return await persist_event(
        request=request,
        verified=verified,
        event_type=event_type,
        payload=payload,
        route=route,
    )


@app.get("/v1/deliveries/{delivery_id}")
def delivery_status(delivery_id: UUID, request: Request) -> dict[str, object]:
    require_management(request)
    result = request.app.state.deliveries.status(delivery_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return result


@app.get("/v1/deliveries/{delivery_id}/changes")
def delivery_changes(delivery_id: UUID, request: Request) -> dict[str, object]:
    require_management(request)
    if request.app.state.deliveries.status(delivery_id) is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "delivery_id": str(delivery_id),
        "changes": request.app.state.deliveries.list_changes(delivery_id),
    }


@app.get("/v1/deliveries/{delivery_id}/transitions")
def delivery_transitions(delivery_id: UUID, request: Request) -> dict[str, object]:
    require_management(request)
    if request.app.state.deliveries.status(delivery_id) is None:
        raise HTTPException(status_code=404, detail="Delivery not found")
    return {
        "delivery_id": str(delivery_id),
        "transitions": request.app.state.deliveries.transitions(delivery_id),
    }


@app.post("/v1/deliveries/{delivery_id}/decisions")
def submit_delivery_decisions(
    delivery_id: UUID, body: DecisionBatch, request: Request
) -> dict[str, object]:
    actor_id = require_management(request)
    try:
        all_resolved = request.app.state.deliveries.submit_decisions(
            delivery_id=delivery_id,
            decisions=[
                ReviewDecision(item.change_id, item.approved, item.reason)
                for item in body.decisions
            ],
            actor_id=actor_id,
            batch_id=uuid4(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "delivery_id": str(delivery_id),
        "all_resolved": all_resolved,
        "changes": request.app.state.deliveries.list_changes(delivery_id),
    }


@app.post("/v1/deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: UUID, request: Request) -> dict[str, object]:
    actor_id = require_management(request)
    try:
        return request.app.state.deliveries.manual_retry(
            delivery_id=delivery_id, actor_id=actor_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/v1/deliveries/{delivery_id}/artifact")
def download_artifact(delivery_id: UUID, request: Request) -> Response:
    require_management(request)
    artifact = request.app.state.deliveries.artifact(delivery_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return Response(
        content=artifact["content"],
        media_type=str(artifact["mime_type"]),
        headers={
            "Content-Disposition": f'attachment; filename="{artifact["filename"]}"',
            "X-Artifact-SHA256": str(artifact["sha256"]),
        },
    )
