"""Route-level API contract tests.

The review route requires a JSON body (the teacher's review instruction).
A missing body must produce FastAPI's structured 422 (detail as an array of
{loc, msg, type}) — the frontend renders that as a meaningful message, and
this test pins the contract so a regression can't silently become
"[object Object]" again.
"""

from fastapi.testclient import TestClient

from app.main import app


def test_review_route_missing_body_returns_structured_422():
    # Body validation runs before auth/workflow lookup, so no session needed.
    with TestClient(app) as client:
        r = client.post("/api/workflow/any/review")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert all(isinstance(d.get("msg"), str) for d in detail)
    assert any(d.get("loc") == ["body"] for d in detail)


def test_review_route_accepts_semantic_configuration_body():
    """A valid semantic configuration passes validation and reaches the auth
    gate (401); raw SuperDocs settings are not part of this public body."""
    with TestClient(app) as client:
        r = client.post(
            "/api/workflow/any/review",
            json={
                "mode": "writing_quality",
                "depth": "thorough",
                "additional_instructions": "Focus on transitions.",
            },
        )
    assert r.status_code == 401  # body valid -> past validation -> auth gate


def test_review_route_rejects_empty_custom_instruction():
    with TestClient(app) as client:
        r = client.post(
            "/api/workflow/any/review",
            json={"mode": "custom", "depth": "standard", "additional_instructions": ""},
        )
    assert r.status_code == 422


def test_decide_route_missing_body_returns_structured_422():
    with TestClient(app) as client:
        r = client.post("/api/workflow/any/decide")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list)
    assert all(isinstance(d.get("msg"), str) for d in detail)


def test_recommended_instruction_endpoint_forbids_annotations():
    """The authoritative instruction the frontend fetches must demand
    replacement-only content — this is the exact regression that let the
    old wording ('showing the original text and the corrected text') reach
    the live engine from the browser path and produce annotated
    replacements."""
    with TestClient(app) as client:
        r = client.get("/api/workflow/recommended-instruction")
    assert r.status_code == 200
    inst = r.json()["instruction"]
    assert "propose the corrected replacement text only" in inst
    assert "'Original:' or 'Corrected:'" in inst
    assert "'Changes made:'" in inst
    assert "'List of changes:'" in inst
    assert "showing the original text and the corrected text" not in inst


def test_logout_requires_post_method():
    """The frontend must POST /api/auth/logout — GET is a 405, never a
    silent success that leaves the session alive."""
    with TestClient(app) as client:
        r = client.get("/api/auth/logout")
    assert r.status_code == 405


def _session_cookie(session_data: dict) -> str:
    """Crafts a classroom_session cookie exactly as the installed
    Starlette SessionMiddleware signs it (itsdangerous TimestampSigner,
    base64 JSON payload), so tests can exercise a session that actually
    holds a session_id."""
    import base64
    import json

    from itsdangerous import TimestampSigner

    from app.core.config import get_settings

    signer = TimestampSigner(str(get_settings().session_secret))
    payload = base64.b64encode(json.dumps(session_data).encode()).decode()
    return signer.sign(payload).decode()


def test_logout_clears_session_cookie_and_invalidates():
    """Real logout round trip: an authenticated session cookie is cleared
    by logout (server-side token deleted + cookie expired), and protected
    routes become unauthorized afterwards."""
    from app.google.oauth import TokenData

    with TestClient(app) as client:
        client.cookies.set("classroom_session", _session_cookie({"session_id": "sid1"}))
        app.state.auth_store.set(
            "sid1",
            TokenData(access_token="tok", refresh_token=None, expires_at=9999999999),
        )
        assert client.get("/api/auth/status").json()["authenticated"] is True

        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        cleared = r.headers.get("set-cookie", "")
        assert "classroom_session" in cleared
        assert "expires=Thu, 01 Jan 1970" in cleared  # Starlette clears via expiry
        import asyncio

        # Token not expired -> get() resolves without refresh, safe to run
        # in a fresh loop.
        assert asyncio.run(app.state.auth_store.get("sid1")) is None  # server token gone

        # The same cookie is no longer a valid session.
        assert client.get("/api/auth/status").json()["authenticated"] is False
        assert client.get("/api/classroom/courses").status_code == 401


def test_state_route_forbidden_for_another_sessions_workflow(monkeypatch):
    """User B (authenticated, different session) must not read User A's
    workflow state via the resume endpoint."""
    from app.api import routes_workflow as rw

    async def fake_auth(request):
        return "tok"

    class Data:
        owner_session_id = "user-a-session"

    class Stub:
        data = Data()

    monkeypatch.setattr(rw, "require_auth", fake_auth)
    monkeypatch.setattr(rw, "_workflow_or_404", lambda request, wid: Stub())
    with TestClient(app) as client:
        r = client.get("/api/workflow/w1/state")
    assert r.status_code == 403
    assert "another session" in r.json()["detail"]
