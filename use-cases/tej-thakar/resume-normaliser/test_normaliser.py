"""
Tests for the resume bulk normaliser — no live API key required.
All outbound SuperDocs HTTP calls are intercepted with respx.

Run:
    pip install -r requirements.txt
    pytest test_normaliser.py -v
"""
import json
from unittest.mock import patch

import pytest
import respx
from httpx import AsyncClient, Response

from main import (
    app,
    normalise_one,
    _try_parse_json,
    _build_normalised_resume,
    RawResume,
)
from config import Settings

# ─── Constants ────────────────────────────────────────────────────────────────

BASE = "https://api.superdocs.app"

GOOD_JSON = json.dumps({
    "full_name": "Jane Doe",
    "email": "jdoe@test.com",
    "phone": None,
    "location": "Bangalore, India",
    "summary": "Experienced software engineer with 5 years in Python.",
    "years_of_experience": 5.0,
    "skills": ["Python", "FastAPI", "SQL"],
    "education": [{"degree": "B.Tech", "field": "CS", "institution": "IIT", "year_completed": 2019}],
    "work_experience": [{"title": "Engineer", "company": "Acme", "start_year": 2019, "end_year": None, "summary": "Backend dev."}],
    "languages": ["English", "Hindi"],
    "normalisation_notes": None,
})


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def settings():
    return Settings(superdocs_api_key="sk_test", superdocs_base_url=BASE)


@pytest.fixture
def resume():
    return RawResume(id="r001", raw_text="Jane Doe\njdoe@test.com\nPython Engineer")


# ─── Unit tests: pure functions ────────────────────────────────────────────────

class TestTryParseJson:
    def test_valid_dict_string(self):
        assert _try_parse_json('{"name": "Alice", "age": 30}') == {"name": "Alice", "age": 30}

    def test_invalid_string(self):
        assert _try_parse_json("not json at all") is None

    def test_empty_string(self):
        assert _try_parse_json("") is None

    def test_json_array_not_dict(self):
        # Arrays parse as JSON but are not dicts; function should return None
        assert _try_parse_json("[1, 2, 3]") is None

    def test_nested_dict(self):
        d = {"a": {"b": 1}}
        assert _try_parse_json(json.dumps(d)) == d


class TestBuildNormalisedResume:
    def test_happy_path_maps_all_fields(self, resume):
        data = json.loads(GOOD_JSON)
        result = _build_normalised_resume(resume, data)
        assert result.status == "normalised"
        assert result.id == "r001"
        assert result.full_name == "Jane Doe"
        assert result.email == "jdoe@test.com"
        assert result.years_of_experience == 5.0
        assert "Python" in result.skills
        assert len(result.education) == 1
        assert len(result.work_experience) == 1
        assert result.error is None

    def test_non_dict_input_returns_error(self, resume):
        result = _build_normalised_resume(resume, "bad input")
        assert result.status == "error"
        assert "unexpected result type" in (result.error or "")

    def test_missing_optional_fields_are_none(self, resume):
        result = _build_normalised_resume(resume, {"full_name": "Alice"})
        assert result.status == "normalised"
        assert result.full_name == "Alice"
        assert result.email is None
        assert result.skills == []


# ─── Integration tests: full SuperDocs flow (mocked) ─────────────────────────

@pytest.mark.asyncio
async def test_normalise_one_happy_path(resume, settings):
    """Job completes on first poll; export returns clean JSON."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j001"})
        )
        rsps.get(f"{BASE}/v1/jobs/j001").mock(
            return_value=Response(200, json={"status": "completed", "result": {}})
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(200, text=GOOD_JSON)
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "normalised"
    assert result.full_name == "Jane Doe"
    assert result.id == "r001"
    assert result.raw_text == resume.raw_text


@pytest.mark.asyncio
async def test_normalise_one_hitl_auto_approve(resume, settings):
    """First poll → HITL gate; auto-approved; second poll → completed."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j002"})
        )
        rsps.get(f"{BASE}/v1/jobs/j002").mock(
            side_effect=[
                Response(200, json={
                    "status": "awaiting_approval",
                    "metadata": {"pending_changes": [{"change_id": "ch-1"}]},
                }),
                Response(200, json={"status": "completed", "result": {}}),
            ]
        )
        rsps.post(url__regex=rf"{BASE}/v1/chat/.+/approve").mock(
            return_value=Response(200, json={"ok": True})
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(200, text=GOOD_JSON)
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "normalised"
    assert result.full_name == "Jane Doe"


@pytest.mark.asyncio
async def test_normalise_one_continue_prompt_auto_continued(resume, settings):
    """continue_prompt pause is auto-continued; job then completes."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j003"})
        )
        rsps.get(f"{BASE}/v1/jobs/j003").mock(
            side_effect=[
                Response(200, json={
                    "status": "awaiting_approval",
                    "metadata": {"awaiting_kind": "continue_prompt"},
                }),
                Response(200, json={"status": "completed", "result": {}}),
            ]
        )
        rsps.post(url__regex=rf"{BASE}/v1/chat/.+/continue").mock(
            return_value=Response(200, json={})
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(200, text=GOOD_JSON)
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "normalised"


@pytest.mark.asyncio
async def test_normalise_one_job_failed(resume, settings):
    """SuperDocs job fails; error is returned in result (batch never raises 500)."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j004"})
        )
        rsps.get(f"{BASE}/v1/jobs/j004").mock(
            return_value=Response(200, json={"status": "failed", "error": "api_error_from_server"})
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "error"
    assert "api_error_from_server" in (result.error or "")


@pytest.mark.asyncio
async def test_normalise_one_export_failure_uses_document_changes(resume, settings):
    """Export endpoint 500s; falls back to document_changes.updated_html."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"job_id": "j005"})
        )
        rsps.get(f"{BASE}/v1/jobs/j005").mock(
            return_value=Response(200, json={
                "status": "completed",
                "result": {
                    "document_changes": {
                        "updated_html": f"<html><body>{GOOD_JSON}</body></html>"
                    }
                },
            })
        )
        rsps.post(f"{BASE}/v1/documents/export").mock(
            return_value=Response(500, text="server error")
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    # Falls back to HTML → strips tags → parses JSON
    assert result.status == "normalised"
    assert result.full_name == "Jane Doe"


@pytest.mark.asyncio
async def test_normalise_one_start_request_fails(resume, settings):
    """401 on session start → error returned immediately (no polling)."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(401, json={"error": "invalid key"})
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "error"
    assert result.id == "r001"


@pytest.mark.asyncio
async def test_normalise_one_no_job_id_in_response(resume, settings):
    """Missing job_id in response → error returned immediately."""
    with patch("main.asyncio.sleep"), respx.mock(assert_all_called=False) as rsps:
        rsps.post(f"{BASE}/v1/chat/async").mock(
            return_value=Response(200, json={"status": "ok"})  # no job_id
        )

        async with AsyncClient(trust_env=False) as client:
            result = await normalise_one(client, resume, settings)

    assert result.status == "error"


# ─── Endpoint smoke tests (no external httpx calls needed) ────────────────────

def test_health_returns_ok():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "resume-normaliser"}


def test_normalize_rejects_empty_list():
    from starlette.testclient import TestClient
    with TestClient(app) as tc:
        resp = tc.post("/normalize", json={"resumes": []})
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"]


def test_normalize_rejects_oversized_batch():
    from starlette.testclient import TestClient
    resumes = [{"id": str(i), "raw_text": "text"} for i in range(51)]
    with TestClient(app) as tc:
        resp = tc.post("/normalize", json={"resumes": resumes})
    assert resp.status_code == 400
    assert "50" in resp.json()["detail"]
