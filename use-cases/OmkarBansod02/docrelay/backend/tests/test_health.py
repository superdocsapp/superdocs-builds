from httpx import ASGITransport, AsyncClient

from docrelay.app import create_app
from docrelay.core.config import Settings


class StubDatabase:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.disposed = False

    async def ping(self, _: float) -> None:
        if self.error:
            raise self.error

    async def dispose(self) -> None:
        self.disposed = True


async def test_liveness_has_no_database_dependency_and_propagates_request_id() -> None:
    database = StubDatabase(error=OSError("must not be called"))
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings, database=database)  # type: ignore[arg-type]
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/health/live", headers={"X-Request-ID": "test-request-123"}
            )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"] == "test-request-123"
    assert database.disposed


async def test_readiness_checks_required_database() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings, database=StubDatabase())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"postgresql": {"status": "ready", "detail": None}},
    }


async def test_readiness_fails_closed_without_leaking_exception_detail() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    database = StubDatabase(error=OSError("password=must-not-leak"))
    app = create_app(settings=settings, database=database)  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert "must-not-leak" not in response.text


async def test_untrusted_request_id_is_replaced() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="test",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )
    app = create_app(settings=settings, database=StubDatabase())  # type: ignore[arg-type]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/live", headers={"X-Request-ID": "bad id value"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad id value"
