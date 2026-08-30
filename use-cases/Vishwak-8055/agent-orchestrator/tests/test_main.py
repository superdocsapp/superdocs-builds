from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_lists_agents():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "security_pii" in body["agents"]


def test_run_agents_flags_pii():
    resp = client.post(
        "/agents/run",
        json={"selected_text": "Email me at test@example.com please.", "command": "scan for pii"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["suggestion_count"] >= 1
    agent_names = {r["agent"] for r in body["results"]}
    assert "security_pii" in agent_names


def test_run_agents_falls_back_to_all_agents_on_unmatched_command():
    resp = client.post(
        "/agents/run",
        json={"selected_text": "Plain paragraph text.", "command": "do something novel"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 4


def test_stream_agents_returns_sse_events():
    with client.stream(
        "POST",
        "/agents/stream",
        json={"selected_text": "Call 415-555-0100 now.", "command": "scan for pii"},
    ) as resp:
        assert resp.status_code == 200
        events = [line for line in resp.iter_lines() if line.startswith("data:")]
    assert any('"event": "routing"' in e for e in events)
    assert any('"event": "done"' in e for e in events)
