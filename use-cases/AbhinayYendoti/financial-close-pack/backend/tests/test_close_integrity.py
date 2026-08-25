"""Regression tests for the data-integrity defects found in the audit."""


def test_endpoints_reject_anonymous_callers(client):
    assert client.get("/api/v1/closes").status_code == 401
    assert client.post("/api/v1/closes", json={}).status_code == 401
    assert client.get("/api/v1/closes/close-demo-march-2026").status_code == 401


def test_demo_session_identity_is_not_client_controlled(client):
    session = client.post("/api/v1/auth/demo-session", json={"name": "Someone Else"}).json()
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session['token']}"}).json()
    assert me["name"] == session["user"]["name"] != "Someone Else"


def test_tampered_session_token_is_rejected(client, auth):
    tampered = auth["Authorization"] + "x"
    assert client.get("/api/v1/auth/me", headers={"Authorization": tampered}).status_code == 401


def test_new_close_is_not_born_with_signed_signoffs(make_close):
    """The old create_close cloned a fixture carrying two APPROVED sign-offs."""
    close = make_close()

    assert [item["status"] for item in close["signoffs"]] == ["PENDING", "PENDING", "PENDING"]
    assert all(item["person"] is None and item["signed_at"] is None for item in close["signoffs"])
    assert close["documents"] == []
    assert [entry["event"] for entry in close["audit"]] == ["CLOSE_CREATED"]


def test_new_close_has_no_reviews_before_generation(make_close):
    """Reviews are produced by generation, so they cannot be approved beforehand."""
    assert make_close()["reviews"] == []


def test_decisions_do_not_leak_across_closes(client, auth, make_close):
    """The old handlers scanned every close by item id, so ids collided across closes."""
    first = make_close(entity="Acme India Pvt Ltd", period="2026-03", due_date="2026-04-05")
    second = make_close(entity="Globex Ltd", period="2026-04", due_date="2026-05-05")

    target = second["signoffs"][2]
    response = client.post(
        f"/api/v1/closes/{second['id']}/signoffs/{target['id']}/approve", headers=auth
    )
    assert response.status_code == 200

    refreshed_first = client.get(f"/api/v1/closes/{first['id']}", headers=auth).json()
    assert all(item["status"] == "PENDING" for item in refreshed_first["signoffs"])

    # And the other close's id is simply not addressable from this one.
    cross = client.post(
        f"/api/v1/closes/{first['id']}/signoffs/{target['id']}/approve", headers=auth
    )
    assert cross.status_code == 404


def test_readiness_survives_a_close_with_no_documents(client, auth, make_close):
    """`docs_ready / len(documents)` used to raise ZeroDivisionError and 500."""
    close = make_close()
    response = client.get(f"/api/v1/closes/{close['id']}/readiness", headers=auth)

    assert response.status_code == 200
    body = response.json()
    assert body["ready_for_close"] is False
    assert isinstance(body["readiness"], int)


def test_actor_is_taken_from_the_session_not_the_request_body(client, auth, make_close):
    """Every handler used to hardcode actor="Abhinay" or read it from the payload."""
    close = make_close()
    signoff = close["signoffs"][0]

    result = client.post(
        f"/api/v1/closes/{close['id']}/signoffs/{signoff['id']}/approve",
        json={"actor": "Somebody Forged"},
        headers=auth,
    ).json()

    me = client.get("/api/v1/auth/me", headers=auth).json()
    assert result["person"] == me["name"]
    assert result["signed_by"] == me["id"]

    trail = client.get(f"/api/v1/closes/{close['id']}/audit", headers=auth).json()
    assert {entry["actor"] for entry in trail} == {me["name"]}


def test_a_signoff_cannot_be_signed_twice(client, auth, make_close):
    close = make_close()
    signoff = close["signoffs"][0]
    path = f"/api/v1/closes/{close['id']}/signoffs/{signoff['id']}/approve"

    assert client.post(path, headers=auth).status_code == 200
    assert client.post(path, headers=auth).status_code == 409


def test_state_survives_a_restart(client, auth, make_close):
    """The old in-memory dict lost every close on restart and per worker."""
    close = make_close(entity="Durable Ltd", period="2026-05", due_date="2026-06-05")

    from backend.app.db import store

    reloaded = store.get_close(close["id"])
    assert reloaded is not None and reloaded["entity"] == "Durable Ltd"
