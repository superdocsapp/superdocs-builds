from typing import Any
from uuid import UUID, uuid4

from httpx import ASGITransport, AsyncClient
from mcp import Client
from starlette.testclient import TestClient

from docrelay.app import create_app
from docrelay.core.config import Settings
from docrelay.mcp import create_mcp_server
from docrelay.services.write_planning import DryRunStatus, DryRunView
from docrelay.services.writeback import ExactFileWriteAuthorizationRequired


class StubDatabase:
    async def dispose(self) -> None:
        return None


class GatePreservingOperations:
    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID]] = []

    async def create_dry_run(self, run_id: UUID, *, proposal_id: UUID | None = None) -> DryRunView:
        del proposal_id
        self.calls.append(("create_dry_run", run_id))
        return DryRunView(
            run_id=run_id,
            proposal_id=None,
            status=DryRunStatus.NOT_APPROVED,
            source=None,
            old_text=None,
            new_text=None,
            structural_location=None,
            operation_count=0,
            operation_types=(),
            provider_operation=None,
            why_safe=(),
            mapping_proof_id=None,
            mapping_proof_sha256=None,
            write_plan_id=None,
            write_plan_sha256=None,
            reason_code="NOT_APPROVED",
            reason="an explicit approved decision is required",
            candidate_count=None,
        )

    async def write_back(self, run_id: UUID) -> Any:
        self.calls.append(("write_back", run_id))
        raise ExactFileWriteAuthorizationRequired(
            "Authorize this exact Google document with Picker before write-back"
        )


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


def test_mcp_streamable_http_is_mounted_with_managed_lifecycle() -> None:
    app = create_app(
        settings=_settings(),
        database=StubDatabase(),  # type: ignore[arg-type]
        machine_operations=GatePreservingOperations(),  # type: ignore[arg-type]
    )
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "docrelay-test", "version": "1"},
        },
    }
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/mcp",
            json=initialize,
            headers={"Accept": "application/json, text/event-stream"},
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "DocRelay"


async def test_rest_and_mcp_share_operations_and_preserve_review_and_authorization_gates() -> None:
    run_id = uuid4()
    operations = GatePreservingOperations()
    app = create_app(
        settings=_settings(),
        database=StubDatabase(),  # type: ignore[arg-type]
        machine_operations=operations,  # type: ignore[arg-type]
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        rest_dry_run = await client.post(f"/api/v1/runs/{run_id}/dry-run")
        rest_write = await client.post(f"/api/v1/runs/{run_id}/write-back")

    assert rest_dry_run.status_code == 200
    assert rest_dry_run.json()["status"] == "NOT_APPROVED"
    assert rest_write.status_code == 409
    assert rest_write.json()["error"]["code"] == "EXACT_FILE_WRITE_AUTHORIZATION_REQUIRED"

    server = create_mcp_server(operations)  # type: ignore[arg-type]
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        mcp_dry_run = await client.call_tool("create_dry_run", {"run_id": str(run_id)})
        mcp_write = await client.call_tool("write_back", {"run_id": str(run_id)})

    assert {
        "list_watch_roots",
        "get_watch_scan",
        "list_scan_runs",
        "get_run",
        "resume_run",
        "submit_review_decisions",
        "create_dry_run",
        "verify_write_authorization",
        "write_back",
        "get_export",
    }.issubset(names)
    assert "batch_approve" not in names
    assert "batch_write_back" not in names
    assert mcp_dry_run.structured_content is not None
    assert mcp_dry_run.structured_content["status"] == "NOT_APPROVED"
    assert mcp_write.is_error
    assert "Authorize this exact Google document" in mcp_write.content[0].text  # type: ignore[union-attr]
    assert operations.calls == [
        ("create_dry_run", run_id),
        ("write_back", run_id),
        ("create_dry_run", run_id),
        ("write_back", run_id),
    ]
