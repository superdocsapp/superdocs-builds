"""HTTP-layer coverage for Milestone 5's two new routes — approve and
export. Session-layer behavior (the actual state machine) is already fully
covered in test_session.py; this file exists because the
exception -> status-code mapping (409 vs 502) is new logic with no other
coverage — a session-layer test proves the right exception type is raised,
not that the route turns it into the right HTTP status.

Same TestClient + direct _sessions registration pattern test_webhooks.py
already establishes. Plain TestClient(app) (no lifespan context manager) is
safe here because every test pre-registers its own session directly into
_sessions, so get_or_create_session's early-return path is always taken and
request.app.state.superdocs_client is never touched.
"""

import base64
import os

os.environ.setdefault("ZOOM_WEBHOOK_SECRET_TOKEN", "test-secret-token")

import httpx
from fastapi.testclient import TestClient

from app.drafting.session import MeetingSession, _sessions
from app.main import app
from app.superdocs.schemas import ExportResult
from app.transcript.manual_provider import ManualTranscriptProvider

# request.app.state.superdocs_client is evaluated as a plain argument
# expression in routes_review.py (get_or_create_session(uuid, request.app.
# state.superdocs_client)) — eagerly, even on a cache-hit that never uses
# the value. Needs lifespan to have run at least once, unlike test_webhooks
# .py's plain TestClient(app), since webhook routes never touch this
# attribute at all. __enter__() without a matching __exit__() is fine here:
# this app.state.superdocs_client is never actually called by these tests
# (every session is pre-registered in _sessions before the request), and
# the process exits with the test run regardless.
client = TestClient(app)
client.__enter__()


class _FakeExportClient:
    """Only export() — approve_draft never touches the SuperDocs client,
    and these tests construct MeetingSession directly with draft_version/
    approved_draft_version already set, bypassing the batch pipeline
    entirely (that pipeline is test_session.py's job, not this file's)."""

    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.calls: list[dict] = []

    async def export(self, *, session_id, format="docx"):
        self.calls.append({"session_id": session_id, "format": format})
        if self.should_fail:
            raise RuntimeError("simulated SuperDocs export failure")
        return ExportResult(
            content=b"fake-docx-bytes",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            warnings=[],
        )


def _register_session(
    meeting_uuid: str,
    *,
    draft_version: int = 0,
    approved_draft_version: int | None = None,
    export_client: _FakeExportClient | None = None,
) -> MeetingSession:
    provider = ManualTranscriptProvider()
    session = MeetingSession(
        meeting_uuid, export_client or _FakeExportClient(), provider, manual_provider=provider
    )
    session.draft_version = draft_version
    session.approved_draft_version = approved_draft_version
    _sessions[meeting_uuid] = session
    return session


def _encode(meeting_uuid: str) -> str:
    return base64.urlsafe_b64encode(meeting_uuid.encode()).decode().rstrip("=")


def test_approve_route_returns_200_and_sets_approved_version():
    _register_session("routes-approve-1", draft_version=1)
    response = client.post(
        f"/api/meetings/{_encode('routes-approve-1')}/approve", json={"draft_version": 1}
    )
    assert response.status_code == 200
    assert response.json() == {"approved_draft_version": 1}
    assert _sessions["routes-approve-1"].approved_draft_version == 1


def test_approve_route_returns_409_on_stale_version():
    _register_session("routes-approve-2", draft_version=2)
    response = client.post(
        f"/api/meetings/{_encode('routes-approve-2')}/approve", json={"draft_version": 1}
    )
    assert response.status_code == 409
    assert _sessions["routes-approve-2"].approved_draft_version is None


def test_export_route_returns_409_when_not_approved():
    _register_session("routes-export-1", draft_version=1, approved_draft_version=None)
    response = client.post(f"/api/meetings/{_encode('routes-export-1')}/export")
    assert response.status_code == 409


def test_approve_then_export_route_returns_docx_bytes_with_content_disposition():
    fake_client = _FakeExportClient()
    _register_session(
        "routes-export-2", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    response = client.post(f"/api/meetings/{_encode('routes-export-2')}/export")
    assert response.status_code == 200
    assert response.content == b"fake-docx-bytes"
    assert "attachment" in response.headers["content-disposition"]
    assert len(fake_client.calls) == 1


def test_export_route_returns_502_on_superdocs_failure():
    fake_client = _FakeExportClient(should_fail=True)
    _register_session(
        "routes-export-3", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    response = client.post(f"/api/meetings/{_encode('routes-export-3')}/export")
    assert response.status_code == 502
    assert "Bearer" not in response.text
    assert "Authorization" not in response.text


def test_download_route_returns_404_when_nothing_exported_yet():
    _register_session("routes-download-1", draft_version=1, approved_draft_version=1)
    response = client.get(f"/api/meetings/{_encode('routes-download-1')}/export/download")
    assert response.status_code == 404


def test_download_route_serves_the_cached_export_without_a_new_superdocs_call():
    fake_client = _FakeExportClient()
    _register_session(
        "routes-download-2", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    export_response = client.post(f"/api/meetings/{_encode('routes-download-2')}/export")
    assert export_response.status_code == 200
    assert len(fake_client.calls) == 1

    download_response = client.get(f"/api/meetings/{_encode('routes-download-2')}/export/download")
    assert download_response.status_code == 200
    assert download_response.content == b"fake-docx-bytes"
    assert "attachment" in download_response.headers["content-disposition"]
    assert len(fake_client.calls) == 1  # unchanged — served from cache, no second SuperDocs call


def test_download_route_still_serves_the_export_after_a_new_unapproved_change():
    # A newer draft version invalidating approval must not erase what was
    # already, genuinely exported — that's still a real, valid document.
    # The frontend (not this route) decides whether to keep advertising the
    # link once approval goes stale.
    fake_client = _FakeExportClient()
    session = _register_session(
        "routes-download-3", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    client.post(f"/api/meetings/{_encode('routes-download-3')}/export")

    session.draft_version = 2  # simulates a new batch landing, approval now stale
    assert session.export_ready is False

    download_response = client.get(f"/api/meetings/{_encode('routes-download-3')}/export/download")
    assert download_response.status_code == 200
    assert download_response.content == b"fake-docx-bytes"


def test_export_route_response_never_contains_the_superdocs_api_key():
    """The 502 handler renders str(exc) directly (routes_review.py) — for
    the httpx.HTTPStatusError SuperDocsClient.export()'s raise_for_status()
    actually raises, that must never include the Authorization header this
    client sends. Constructs a real httpx.HTTPStatusError over a real
    request carrying the header, exactly like the live client does, rather
    than trusting a hand-rolled fake to prove something about a real
    library's own __str__ behavior."""
    fake_secret = "sk_test_should_never_appear_in_any_response_abc123"
    request = httpx.Request(
        "POST",
        "https://api.superdocs.app/v1/documents/export",
        headers={"Authorization": f"Bearer {fake_secret}"},
    )
    response = httpx.Response(500, request=request, text="internal error")
    try:
        response.raise_for_status()
        rendered = ""
    except httpx.HTTPStatusError as exc:
        rendered = str(exc)

    assert fake_secret not in rendered


# --- share links: the document has to REACH people, not just export -------
#
# The assigned build's card says the document is "finished AND SENT while the
# call is still open... nobody has to reconcile it later". Export writes a
# file to the host's own disk, which reaches nobody. A share link is what
# closes that: the host pastes it into Zoom chat and every participant has
# the document before they leave.
#
# What this must never do:
#   1. hand out a document nobody approved
#   2. mint a guessable token
#   3. keep serving a link after the meeting data is cleared


def test_share_route_returns_409_when_nothing_is_approved():
    _register_session("routes-share-1", draft_version=1, approved_draft_version=None)
    r = client.post(f"/api/meetings/{_encode('routes-share-1')}/share")
    assert r.status_code == 409, "an unapproved document must never be shareable"


def test_share_route_mints_a_link_for_an_approved_document():
    fake_client = _FakeExportClient()
    _register_session(
        "routes-share-2", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    client.post(f"/api/meetings/{_encode('routes-share-2')}/export")

    r = client.post(f"/api/meetings/{_encode('routes-share-2')}/share")
    assert r.status_code == 200
    body = r.json()
    assert len(body["token"]) >= 32, "share token must not be guessable"
    assert body["url"].endswith(body["token"])

    got = client.get(f"/api/share/{body['token']}")
    assert got.status_code == 200
    assert got.content == b"fake-docx-bytes"
    assert "attachment" in got.headers["content-disposition"]


def test_share_route_exports_first_when_nothing_was_exported_yet():
    """Approved but not yet exported: sharing should still work."""
    fake_client = _FakeExportClient()
    _register_session(
        "routes-share-3", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    r = client.post(f"/api/meetings/{_encode('routes-share-3')}/share")
    assert r.status_code == 200
    assert client.get(f"/api/share/{r.json()['token']}").content == b"fake-docx-bytes"


def test_unknown_share_token_is_404():
    assert client.get("/api/share/not-a-real-token-at-all").status_code == 404


def test_clearing_the_meeting_revokes_its_share_links():
    """A stale link must not outlive the meeting it came from."""
    fake_client = _FakeExportClient()
    _register_session(
        "routes-share-4", draft_version=1, approved_draft_version=1, export_client=fake_client
    )
    token = client.post(f"/api/meetings/{_encode('routes-share-4')}/share").json()["token"]
    assert client.get(f"/api/share/{token}").status_code == 200
    client.post(f"/api/meetings/{_encode('routes-share-4')}/clear")
    assert client.get(f"/api/share/{token}").status_code == 404
