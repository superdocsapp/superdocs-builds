def test_health_check(client):
    """
    Test that the health check endpoint returns 200 and healthy statuses.
    """
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "healthy"
    assert "environment" in data
