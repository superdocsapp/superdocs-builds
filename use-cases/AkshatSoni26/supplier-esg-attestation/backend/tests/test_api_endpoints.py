import pytest


@pytest.mark.asyncio
async def test_api_list_suppliers(client):
    """Test GET /api/v1/suppliers"""
    response = await client.get("/api/v1/suppliers")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 5
    assert any(s["code"] == "SUP-ACME-01" for s in data)


@pytest.mark.asyncio
async def test_api_issue_questionnaire(client):
    """Test POST /api/v1/issuance/issue"""
    payload = {
        "supplier_id": "sup-003-zenith",
        "cycle_year": 2026
    }
    response = await client.post("/api/v1/issuance/issue", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["supplier_id"] == "sup-003-zenith"
    assert data["tier"] == "TIER_3_COMMODITY"
    assert "ANNEX T3" in data["document_content_markdown"]
    assert "ANNEX R-US" in data["document_content_markdown"]


@pytest.mark.asyncio
async def test_api_programme_report_summary(client):
    """Test GET /api/v1/reports/programme-summary"""
    response = await client.get("/api/v1/reports/programme-summary?cycle_year=2026")
    assert response.status_code == 200
    data = response.json()
    assert data["cycle_year"] == 2026
    assert data["total_suppliers_invited"] == 5
    assert "pillar_averages" in data
    assert "tier_distribution" in data
    assert "regional_distribution" in data


@pytest.mark.asyncio
async def test_api_review_gate_submission(client):
    """Test POST /api/v1/review/{assessment_id}/submit"""
    payload = {
        "is_approved": True,
        "approved_by": "Compliance Lead",
        "finding_decisions": [
            {
                "finding_id": "find-acme-01",
                "review_decision": "ACCEPTED",
                "review_notes": "Scope 2 remediation mandatory."
            }
        ]
    }
    response = await client.post("/api/v1/review/ass-acme-2026/submit", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["is_approved"] is True
    assert data["approved_by"] == "Compliance Lead"
