from __future__ import annotations

import base64
import io
import zipfile

import httpx
import pytest

from redline.core.negotiation import NegotiationService
from redline.core.store import Store
from redline.main import create_app
from redline.slack.simulator import InMemoryMessenger
from redline.superdocs.client import SuperDocsClient
from redline.superdocs.fake import FakeSuperDocs
from tests.conftest import CAP_INSTRUCTION, make_contract_docx, make_settings


@pytest.fixture
def app(tmp_path):
    settings = make_settings(tmp_path)
    store = Store(settings.database_path)
    client = SuperDocsClient(FakeSuperDocs())
    service = NegotiationService(settings, store, client, InMemoryMessenger())
    return create_app(service), settings


async def test_multipart_upload_and_document_and_search_endpoints(app):
    fastapi_app, settings = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with fastapi_app.router.lifespan_context(fastapi_app):
            # a real multipart upload, not a base64 JSON string
            resp = await client.post(
                "/deals/upload",
                data={"name": "Acme-Globex MSA", "side": "vendor", "user": "U_VENDOR"},
                files={
                    "file": (
                        "MSA.docx",
                        make_contract_docx(),
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    )
                },
            )
            assert resp.status_code == 200, resp.text
            deal_id = resp.json()["deal_id"]

            resp = await client.post(
                f"/deals/{deal_id}/documents",
                data={"side": "customer", "user": "U_CUSTOMER", "role": "amendment"},
                files={
                    "file": (
                        "Amendment_1.docx",
                        make_contract_docx(),
                        "application/octet-stream",
                    )
                },
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["role"] == "amendment"

            resp = await client.get(f"/deals/{deal_id}/documents")
            assert resp.status_code == 200
            filenames = [d["filename"] for d in resp.json()["documents"]]
            assert filenames == ["MSA.docx", "Amendment_1.docx"]

            resp = await client.post(
                f"/deals/{deal_id}/notes",
                json={
                    "side": "vendor",
                    "author": "U_VENDOR",
                    "body": "internal walkaway number is two fifty",
                },
            )
            assert resp.status_code == 200

            # search from the shared channel must not surface the internal note
            resp = await client.get(
                f"/deals/{deal_id}/search",
                params={
                    "q": "walkaway",
                    "side": "vendor",
                    "source_channel_id": settings.shared_channel,
                },
            )
            assert resp.status_code == 200, resp.text
            assert all(h["kind"] != "internal_note" for h in resp.json()["hits"])

            # the same search from the vendor's own internal channel does
            resp = await client.get(
                f"/deals/{deal_id}/search",
                params={
                    "q": "walkaway",
                    "side": "vendor",
                    "source_channel_id": settings.vendor_internal_channel,
                },
            )
            assert any(h["kind"] == "internal_note" for h in resp.json()["hits"])

            resp = await client.get(
                f"/deals/{deal_id}/search",
                params={
                    "q": "liability",
                    "side": "vendor",
                    "source_channel_id": settings.shared_channel,
                },
            )
            assert resp.json()["hits"], "should find the liability clause in the document"


async def test_rest_surface_drives_full_negotiation_end_to_end(app):
    fastapi_app, settings = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with fastapi_app.router.lifespan_context(fastapi_app):
            content_b64 = base64.b64encode(make_contract_docx()).decode("ascii")
            resp = await client.post(
                "/deals",
                json={
                    "name": "Acme-Globex MSA",
                    "side": "vendor",
                    "user": "U_VENDOR",
                    "filename": "MSA.docx",
                    "file_base64": content_b64,
                },
            )
            assert resp.status_code == 200, resp.text
            deal_id = resp.json()["deal_id"]
            assert resp.json()["current_version"] == "v1"

            resp = await client.post(
                f"/deals/{deal_id}/propose",
                json={
                    "side": "vendor",
                    "user": "U_VENDOR",
                    "instruction": CAP_INSTRUCTION,
                    "source_channel_id": settings.shared_channel,
                },
            )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["state"] == "awaiting_review"
            proposals = body["proposals"]
            assert len(proposals) >= 1
            proposal_id = proposals[0]["id"]

            # a machine driving this end-to-end must be able to call approval explicitly,
            # for both sides, with no human clicking through a UI
            resp = await client.post(
                f"/deals/{deal_id}/proposals/{proposal_id}/decide",
                json={"side": "vendor", "user": "U_VENDOR", "approved": True},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["state"] == "pending"

            resp = await client.post(
                f"/deals/{deal_id}/proposals/{proposal_id}/decide",
                json={"side": "customer", "user": "U_CUSTOMER", "approved": True},
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["state"] == "committed"

            resp = await client.get(f"/deals/{deal_id}/status")
            assert resp.status_code == 200
            assert resp.json()["current_version"] != "v1"

            resp = await client.get(f"/deals/{deal_id}/history")
            assert resp.status_code == 200
            assert any("job_completed" in line for line in resp.json()["lines"])

            resp = await client.post(
                f"/deals/{deal_id}/notes",
                json={"side": "vendor", "author": "U_VENDOR", "body": "internal only, never leaks"},
            )
            assert resp.status_code == 200
            assert resp.json()["ok"] is True

            resp = await client.post(f"/deals/{deal_id}/export", json={"kind": "clean"})
            assert resp.status_code == 200
            clean_bytes = base64.b64decode(resp.json()["content_base64"])
            assert clean_bytes[:2] == b"PK"
            with zipfile.ZipFile(io.BytesIO(clean_bytes)) as archive:
                assert "word/document.xml" in archive.namelist()

            resp = await client.post(f"/deals/{deal_id}/export", json={"kind": "redline"})
            assert resp.status_code == 200
            redline_bytes = base64.b64decode(resp.json()["content_base64"])
            assert redline_bytes[:2] == b"PK"


async def test_rest_surface_rejects_provenance_violation(app):
    fastapi_app, settings = app
    transport = httpx.ASGITransport(app=fastapi_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with fastapi_app.router.lifespan_context(fastapi_app):
            content_b64 = base64.b64encode(make_contract_docx()).decode("ascii")
            resp = await client.post(
                "/deals",
                json={
                    "name": "Deal",
                    "side": "vendor",
                    "user": "U_VENDOR",
                    "filename": "MSA.docx",
                    "file_base64": content_b64,
                },
            )
            deal_id = resp.json()["deal_id"]

            resp = await client.post(
                f"/deals/{deal_id}/propose",
                json={
                    "side": "vendor",
                    "user": "U_VENDOR",
                    "instruction": CAP_INSTRUCTION,
                    "source_channel_id": settings.vendor_internal_channel,
                },
            )
            assert resp.status_code == 403
