import pytest
import httpx
from src.main import app


@pytest.mark.anyio
async def test_health_returns_200():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_demo_seed_endpoint_calls_seed_demo(monkeypatch):
    class FakeSeedModule:
        @staticmethod
        def seed_demo():
            return {
                "status": "seeded",
                "pile_id": "pile-1",
                "run_id": "run-1",
                "document_count": 5,
                "conflicts": [],
            }

    monkeypatch.setattr("src.main._load_seed_demo_module", lambda: FakeSeedModule)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/demo/seed")

    assert response.status_code == 200
    assert response.json()["document_count"] == 5
