import time
from uuid import uuid4

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import Response

from app.gateway.audit import DEFAULT_AUDIT_LOGGER
from app.gateway.client import DownstreamUnavailableError, SuperDocsClient
from app.gateway.pipeline import DEFAULT_GATEWAY_POLICY_PIPELINE, PolicyDecision
from app.gateway.sensitive import SensitiveAction, scan_sensitive_content


router = APIRouter(prefix="/gateway", tags=["Policy Gateway"])
client = SuperDocsClient()
pipeline = DEFAULT_GATEWAY_POLICY_PIPELINE


TEXT_SCAN_CHUNK_SIZE = 64 * 1024
TEXT_SCAN_OVERLAP = 512


def _audit(
    request_id: str,
    team: str,
    tool: str,
    allowed: bool,
    status_code: int,
    started: float,
) -> None:
    if pipeline.policy.audit_enabled:
        DEFAULT_AUDIT_LOGGER.record(
            request_id=request_id,
            team=team,
            tool=tool,
            allowed=allowed,
            status_code=status_code,
            duration_ms=(time.perf_counter() - started) * 1000,
        )


def _raise_decision(decision: PolicyDecision) -> None:
    raise HTTPException(
        status_code=decision.status_code,
        detail={
            "error": decision.error,
            "categories": list(decision.categories),
        },
    )


def _downstream() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "error": "DOWNSTREAM_UNAVAILABLE",
            "message": "SuperDocs is temporarily unavailable.",
        },
    )


def _content(payload: dict, fields: tuple[str, ...]) -> str:
    return "\n".join(str(payload.get(field, "")) for field in fields)


def _mask_fields(payload: dict, fields: tuple[str, ...]) -> dict:
    if not pipeline.policy.sensitive_policy.enabled:
        return payload

    if pipeline.policy.sensitive_policy.action != SensitiveAction.MASK.value:
        return payload

    for field in fields:
        value = payload.get(field)
        if isinstance(value, str):
            payload[field] = scan_sensitive_content(
                value,
                action=SensitiveAction.MASK,
            ).content
    return payload


def _policy_error_allowed(error: HTTPException) -> bool:
    return error.status_code == 503


@router.post("/v1/chat")
async def gateway_chat(
    payload: dict,
    x_team_id: str = Header(default="default"),
):
    request_id = str(uuid4())
    started = time.perf_counter()
    tool = "chat"

    try:
        fields = ("message", "document_html")
        decision = pipeline.evaluate(
            team_id=x_team_id,
            tool=tool,
            content=_content(payload, fields),
        )
        if not decision.allowed:
            _raise_decision(decision)

        payload = _mask_fields(payload, fields)
        response = await client.request(
            method="POST",
            path="/v1/chat",
            json=payload,
        )
        if response.status_code >= 400:
            raise HTTPException(
                response.status_code,
                detail=response.text,
            )

        _audit(request_id, x_team_id, tool, True, response.status_code, started)
        return response.json()

    except DownstreamUnavailableError as exc:
        error = _downstream()
        _audit(request_id, x_team_id, tool, True, error.status_code, started)
        raise error from exc
    except HTTPException as exc:
        _audit(
            request_id,
            x_team_id,
            tool,
            _policy_error_allowed(exc),
            exc.status_code,
            started,
        )
        raise


@router.post("/v1/chat/{session_id}/approve")
async def gateway_approve(
    session_id: str,
    payload: dict | None = None,
    x_team_id: str = Header(default="default"),
):
    request_id = str(uuid4())
    started = time.perf_counter()
    tool = "approve"
    payload = payload or {}

    try:
        fields = ("message", "comment", "document_html")
        decision = pipeline.evaluate(
            team_id=x_team_id,
            tool=tool,
            content=_content(payload, fields),
        )
        if not decision.allowed:
            _raise_decision(decision)

        payload = _mask_fields(payload, fields)
        response = await client.request(
            method="POST",
            path=f"/v1/chat/{session_id}/approve",
            json=payload,
        )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, detail=response.text)

        _audit(request_id, x_team_id, tool, True, response.status_code, started)
        return response.json()

    except DownstreamUnavailableError as exc:
        error = _downstream()
        _audit(request_id, x_team_id, tool, True, error.status_code, started)
        raise error from exc
    except HTTPException as exc:
        _audit(request_id, x_team_id, tool, _policy_error_allowed(exc), exc.status_code, started)
        raise


@router.post("/v1/documents/export")
async def gateway_export(
    payload: dict,
    x_team_id: str = Header(default="default"),
):
    request_id = str(uuid4())
    started = time.perf_counter()
    tool = "export"

    try:
        fields = ("html", "document_html", "content")
        decision = pipeline.evaluate(
            team_id=x_team_id,
            tool=tool,
            content=_content(payload, fields),
        )
        if not decision.allowed:
            _raise_decision(decision)

        payload = _mask_fields(payload, fields)
        response = await client.request(
            method="POST",
            path="/v1/documents/export",
            json=payload,
        )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, detail=response.text)

        _audit(request_id, x_team_id, tool, True, response.status_code, started)
        return Response(
            content=response.content,
            media_type=response.headers.get(
                "content-type",
                "application/octet-stream",
            ),
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() == "content-disposition"
            },
        )

    except DownstreamUnavailableError as exc:
        error = _downstream()
        _audit(request_id, x_team_id, tool, True, error.status_code, started)
        raise error from exc
    except HTTPException as exc:
        _audit(request_id, x_team_id, tool, _policy_error_allowed(exc), exc.status_code, started)
        raise


@router.post("/v1/documents/upload")
async def gateway_upload(
    file: UploadFile = File(...),
    x_team_id: str = Header(default="default"),
):
    request_id = str(uuid4())
    started = time.perf_counter()
    tool = "upload"

    try:
        file.file.seek(0)
        carry = ""
        matched_categories: set[str] = set()

        while True:
            chunk = file.file.read(TEXT_SCAN_CHUNK_SIZE)
            if not chunk:
                break

            text = carry + chunk.decode("utf-8", errors="ignore")
            result = scan_sensitive_content(
                text,
                action=SensitiveAction.BLOCK,
            )
            matched_categories.update(
                match.category for match in result.matches
            )

            if not result.allowed and matched_categories:
                decision = PolicyDecision(
                    allowed=False,
                    status_code=403,
                    error="SENSITIVE_CONTENT_BLOCKED",
                    categories=tuple(sorted(matched_categories)),
                )
                _raise_decision(decision)

            carry = text[-TEXT_SCAN_OVERLAP:]

        file.file.seek(0)
        decision = pipeline.evaluate(
            team_id=x_team_id,
            tool=tool,
            content="",
        )
        if not decision.allowed:
            _raise_decision(decision)

        response = await client.request(
            method="POST",
            path="/v1/documents/upload",
            files={
                "file": (
                    file.filename or "upload",
                    file.file,
                    file.content_type or "application/octet-stream",
                )
            },
        )
        if response.status_code >= 400:
            raise HTTPException(response.status_code, detail=response.text)

        _audit(request_id, x_team_id, tool, True, response.status_code, started)
        return response.json()

    except DownstreamUnavailableError as exc:
        error = _downstream()
        _audit(request_id, x_team_id, tool, True, error.status_code, started)
        raise error from exc
    except HTTPException as exc:
        _audit(request_id, x_team_id, tool, _policy_error_allowed(exc), exc.status_code, started)
        raise
