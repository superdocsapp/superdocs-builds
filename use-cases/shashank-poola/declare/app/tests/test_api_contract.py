from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_health_contract_is_available_to_the_frontend():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"success": True, "service": "declare"}


def test_local_nextjs_origin_is_allowed_by_cors():
    response = client.options(
        "/api/declare/analyze",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_invalid_request_uses_the_frontend_error_envelope():
    response = client.post("/api/declare/analyze", json={})
    assert response.status_code == 400
    assert response.json()["success"] is False
    assert response.json()["error"] == "INVALID_ANALYZE_REQUEST_OR_GLM_RESPONSE"
