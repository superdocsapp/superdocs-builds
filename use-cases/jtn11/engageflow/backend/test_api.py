#!/usr/bin/env python3
"""
Test script for EngageFlow FastAPI REST Server.
Tests endpoints directly via FastAPI TestClient.
"""
import sys
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app

def main():
    print("==========================================")
    print(" EngageFlow FastAPI Endpoint Test         ")
    print("==========================================")

    client = TestClient(app)

    # 1. Health check endpoint
    resp = client.get("/health")
    print(f"GET /health: {resp.status_code} -> {resp.json()}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"

    # 2. Periods endpoint
    resp = client.get("/api/periods")
    print(f"GET /api/periods: {resp.status_code} -> {resp.json()}")
    assert resp.status_code == 200
    assert len(resp.json()["periods"]) >= 2

    # 3. Generate Report pipeline endpoint
    payload = {
        "current_period": "period_2",
        "previous_period": "period_1"
    }
    resp = client.post("/api/generate-report", json=payload)
    print(f"POST /api/generate-report: {resp.status_code}")
    assert resp.status_code == 200

    data = resp.json()
    assert data["success"] is True
    assert "report_markdown" in data
    assert data["overall_status"] == "RED"
    assert "superdocs_integration" in data

    print(f"✅ Generated Report Length: {len(data['report_markdown'])} chars")
    print(f"✅ SuperDocs Run ID: {data['superdocs_integration'].get('superdocs_run', {}).get('run_id')}")

    print("\n🎉 Step 5 Test PASSED! FastAPI application server and REST endpoints verified.")

if __name__ == "__main__":
    main()
