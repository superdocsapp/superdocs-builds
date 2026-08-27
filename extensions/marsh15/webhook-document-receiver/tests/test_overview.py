from fastapi.testclient import TestClient

from app.main import app


def test_overview_allows_its_inline_styles_and_keeps_security_headers() -> None:
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "Authenticated events become reviewed documents" in response.text
    assert "style-src 'unsafe-inline'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


def test_docs_are_not_broken_by_api_only_csp() -> None:
    response = TestClient(app).get("/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
