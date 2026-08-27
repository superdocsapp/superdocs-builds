"""The HTTP surface the add-on calls.

Driven through ASGI with a fake SuperDocs client, so these run offline like
everything else. What matters here is the contract Apps Script depends on:
propose never writes, commit honours decisions, and failures come back with a
cause and a fix rather than a bare status code.
"""

from __future__ import annotations

import collections

import httpx
import pytest
from fakes import QUARTERLY, FakeClient

from narrative_report import api as api_module
from narrative_report.store import ReportStore

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(tmp_path):
    """The real app with its lifespan bypassed and a fake client injected."""
    application = api_module.app
    application.state.store = ReportStore(tmp_path / "reports")
    application.state.locks = collections.defaultdict(__import__("asyncio").Lock)
    application.state.client = FakeClient()
    return application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


PAYLOAD = {"values": QUARTERLY, "sheet": "P&L", "a1": "B2:F6", "report_id": "api-1"}


class TestPropose:
    async def test_returns_a_reviewable_proposal(self, client):
        r = await client.post("/reports/propose", json=PAYLOAD)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "awaiting_review"
        assert len(body["sections"]) == 3
        assert body["operations_spent"] == 1
        assert body["stage_seconds"]

    async def test_writes_nothing_until_commit(self, client, app):
        await client.post("/reports/propose", json=PAYLOAD)
        assert app.state.client.exports == []
        assert app.state.store.load_manifest("api-1") is None

    async def test_sections_carry_what_the_sidebar_renders(self, client):
        body = (await client.post("/reports/propose", json=PAYLOAD)).json()
        for section in body["sections"]:
            assert {"id", "heading", "action", "reason", "html", "problems"} <= set(section)

    async def test_an_unreadable_selection_names_the_fix(self, client):
        r = await client.post(
            "/reports/propose", json={"values": [["only one row"]], "sheet": "S", "a1": "A1"}
        )
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["cause"] and detail["fix"]

    async def test_a_selection_with_no_numbers_is_refused(self, client):
        r = await client.post(
            "/reports/propose",
            json={"values": [["Item", "Q1"], ["Notes", "hello"]], "sheet": "S", "a1": "A1:B2"},
        )
        assert r.status_code == 422


class TestCommit:
    async def test_applies_accepted_sections_and_exports(self, client, app):
        proposal = (await client.post("/reports/propose", json=PAYLOAD)).json()
        decisions = {s["id"]: True for s in proposal["sections"]}

        r = await client.post("/reports/api-1/commit", json={"decisions": decisions})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "committed"
        assert body["exported_bytes"] > 0
        assert body["download"] == "/reports/api-1/download?format=docx"
        assert app.state.store.load_manifest("api-1") is not None

    async def test_rejection_is_honoured(self, client, app):
        proposal = (await client.post("/reports/propose", json=PAYLOAD)).json()
        decisions = {s["id"]: s["id"] != "movers" for s in proposal["sections"]}
        await client.post("/reports/api-1/commit", json={"decisions": decisions})

        kept = {s.id for s in app.state.store.load_manifest("api-1").sections}
        assert "movers" not in kept and "summary" in kept

    async def test_committing_without_a_proposal_conflicts(self, client):
        r = await client.post("/reports/nope/commit", json={"decisions": {"summary": True}})
        assert r.status_code == 409
        assert r.json()["detail"]["fix"]

    async def test_unknown_format_is_refused_before_any_work(self, client):
        await client.post("/reports/propose", json=PAYLOAD)
        r = await client.post(
            "/reports/api-1/commit", json={"decisions": {}, "format": "wingdings"}
        )
        assert r.status_code == 422
        assert "docx" in r.json()["detail"]["fix"]


class TestDownload:
    async def test_serves_the_export_with_the_right_mime(self, client):
        proposal = (await client.post("/reports/propose", json=PAYLOAD)).json()
        await client.post(
            "/reports/api-1/commit",
            json={"decisions": {s["id"]: True for s in proposal["sections"]}},
        )
        r = await client.get("/reports/api-1/download?format=docx")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        assert 'filename="api-1.docx"' in r.headers["content-disposition"]

    async def test_missing_export_is_a_404_with_a_fix(self, client):
        r = await client.get("/reports/ghost/download")
        assert r.status_code == 404
        assert r.json()["detail"]["fix"]


class TestReportState:
    async def test_reports_awaiting_review(self, client):
        await client.post("/reports/propose", json=PAYLOAD)
        body = (await client.get("/reports/api-1")).json()
        assert body["awaiting_review"] is True
        assert body["revision"] == 0  # nothing committed yet

    async def test_unknown_report_is_a_404(self, client):
        assert (await client.get("/reports/ghost")).status_code == 404

    async def test_listing_reports(self, client):
        proposal = (await client.post("/reports/propose", json=PAYLOAD)).json()
        await client.post(
            "/reports/api-1/commit",
            json={"decisions": {s["id"]: True for s in proposal["sections"]}},
        )
        assert "api-1" in (await client.get("/reports")).json()["reports"]


class TestAuth:
    async def test_token_is_enforced_when_configured(self, client, monkeypatch):
        monkeypatch.setattr(api_module, "ADDON_TOKEN", "secret")
        assert (await client.post("/reports/propose", json=PAYLOAD)).status_code == 401
        r = await client.post(
            "/reports/propose", json=PAYLOAD, headers={"X-Addon-Token": "secret"}
        )
        assert r.status_code == 200

    async def test_open_when_unconfigured(self, client, monkeypatch):
        monkeypatch.setattr(api_module, "ADDON_TOKEN", None)
        assert (await client.post("/reports/propose", json=PAYLOAD)).status_code == 200
