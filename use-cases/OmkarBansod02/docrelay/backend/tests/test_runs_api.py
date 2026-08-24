from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from docrelay.app import create_app
from docrelay.core.config import Settings


class StubDatabase:
    async def dispose(self) -> None:
        return None


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


async def test_phase3_machine_routes_exist_and_unconfigured_error_is_safe() -> None:
    app = create_app(settings=_settings(), database=StubDatabase())  # type: ignore[arg-type]
    run_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [
            await client.get("/api/v1/runs"),
            await client.get(f"/api/v1/runs/{run_id}"),
            await client.post(f"/api/v1/runs/{run_id}/resume"),
            await client.get(f"/api/v1/runs/{run_id}/proposals"),
            await client.get(f"/api/v1/runs/{run_id}/export"),
        ]
        openapi = (await client.get("/api/openapi.json")).json()

    assert all(response.status_code == 503 for response in responses)
    assert all(
        response.json()["error"]["code"] == "SUPERDOCS_NOT_CONFIGURED" for response in responses
    )
    serialized = "".join(response.text for response in responses).lower()
    for forbidden in ("api_key", "authorization", "access_token", "refresh_token"):
        assert forbidden not in serialized
    expected_paths = {
        "/api/v1/runs",
        "/api/v1/runs/{run_id}",
        "/api/v1/runs/{run_id}/resume",
        "/api/v1/runs/{run_id}/proposals",
        "/api/v1/runs/{run_id}/decisions",
        "/api/v1/runs/{run_id}/continue",
        "/api/v1/runs/{run_id}/export",
        "/api/v1/runs/{run_id}/export/content",
        "/api/v1/runs/{run_id}/summary",
    }
    assert expected_paths.issubset(openapi["paths"])
    summary_properties = openapi["components"]["schemas"]["RunSummary"]["properties"]
    assert {"instruction", "proposal_count", "created_at"}.issubset(summary_properties)


async def test_phase6_routes_accept_no_browser_provider_operations() -> None:
    app = create_app(settings=_settings(), database=StubDatabase())  # type: ignore[arg-type]
    run_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        write = await client.post(f"/api/v1/runs/{run_id}/write-back")
        openapi = (await client.get("/api/openapi.json")).json()

    write_path = openapi["paths"]["/api/v1/runs/{run_id}/write-back"]["post"]
    assert "requestBody" not in write_path
    write_schema = openapi["components"]["schemas"]["WriteBackView"]
    assert "verified_preview" in write_schema["properties"]
    assert "/api/v1/runs/{run_id}/conflict-decision" in openapi["paths"]
    assert write.status_code == 503
    serialized = write.text.lower()
    for forbidden in ("authorization", "access_token", "refresh_token", "raw_payload"):
        assert forbidden not in serialized


async def test_watch_machine_routes_are_exposed_without_a_demo_execution_path() -> None:
    app = create_app(settings=_settings(), database=StubDatabase())  # type: ignore[arg-type]
    watch_id = uuid4()
    run_id = uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        unavailable = await client.get("/api/v1/watches")
        write_authorization = await client.post(
            f"/api/v1/runs/{run_id}/write-authorization",
            json={"file_id": "picker-file-id"},
        )
        openapi = (await client.get("/api/openapi.json")).json()

    expected_paths = {
        "/api/v1/watches",
        "/api/v1/watches/{watch_id}",
        "/api/v1/watches/{watch_id}/schedule",
        "/api/v1/watches/{watch_id}/rules",
        "/api/v1/watches/{watch_id}/scans",
        "/api/v1/watches/{watch_id}/scans/{scan_id}/items",
        "/api/v1/watches/{watch_id}/scans/{scan_id}",
        "/api/v1/watches/{watch_id}/scans/{scan_id}/runs",
        "/api/v1/watches/{watch_id}/items",
        "/api/v1/watches/{watch_id}/runs",
        "/api/v1/runs/{run_id}/write-authorization",
    }
    assert expected_paths.issubset(openapi["paths"])
    assert unavailable.status_code == 503
    assert write_authorization.status_code == 503
    assert unavailable.json()["error"]["code"] == "GOOGLE_OAUTH_NOT_CONFIGURED"
    serialized = unavailable.text + write_authorization.text + str(watch_id)
    for forbidden in ("access_token", "refresh_token", "client_secret"):
        assert forbidden not in serialized.lower()
