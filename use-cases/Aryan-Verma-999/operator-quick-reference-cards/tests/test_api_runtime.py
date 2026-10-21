import asyncio

import fitz
import httpx

from linecard.api import create_app


def test_demo_api_blocks_missing_evidence_then_postflights_and_downloads_verified_pdf():
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://linecard.test") as client:
            initial = await client.get("/api/demo")
            assert initial.status_code == 200
            assert initial.json()["included_count"] == initial.json()["required_count"] == 6
            assert initial.json()["card"]["safety"]["included"] is True

            rejected = await client.post("/api/demo/evidence/SAFE-001", json={"included": False})
            assert rejected.status_code == 200
            assert rejected.json()["included_count"] == 5
            assert rejected.json()["card"]["safety"]["included"] is False
            assert "Evidence excluded" in rejected.json()["card"]["safety"]["text"]

            blocked = await client.post("/api/demo/verify")
            assert blocked.status_code == 200
            assert blocked.json()["verification"]["status"] == "BLOCKED"
            assert "SAFE-001" in blocked.json()["verification"]["checks"][0]["reason"]
            assert (await client.post("/api/demo/export")).status_code == 409

            assert (await client.post("/api/demo/evidence/SAFE-001", json={"included": True})).status_code == 200
            verified = await client.post("/api/demo/verify")
            assert verified.status_code == 200
            assert verified.json()["verification"]["status"] == "PASS"

            exported = await client.post("/api/demo/export")
            assert exported.status_code == 200
            assert exported.json()["postflight"]["status"] == "PASS"
            assert len(exported.json()["pdf_sha256"]) == 64
            assert exported.json()["page_count"] == 2
            assert exported.json()["included_evidence_ids"] == ["RESTART-001", "SAFE-001", "SPEC-001", "STEP-001", "STEP-002", "STEP-003"]
            pdf = await client.get(exported.json()["download_url"])
            assert pdf.status_code == 200 and pdf.headers["content-type"].startswith("application/pdf")
            rendered = fitz.open(stream=pdf.content, filetype="pdf")
            assert len(rendered) == 2
            assert "Clear a jam on the infeed" in "\n".join(page.get_text() for page in rendered)
            assert "Guard fastener torque: 24 N·m ± 2 N·m." in "\n".join(page.get_text() for page in rendered)

    asyncio.run(exercise())


def test_demo_api_keeps_live_provider_defect_disclosed_and_serves_synthetic_manual_only():
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://linecard.test") as client:
            payload = (await client.get("/api/demo")).json()
            assert "blocked" in payload["live_limitations"].lower()
            manual = await client.get(payload["manual_url"])
            assert manual.status_code == 200
            assert manual.headers["content-type"].startswith("application/pdf")
            preview = await client.get("/api/demo/evidence/SAFE-001/preview")
            assert preview.status_code == 200
            assert preview.headers["content-type"].startswith("image/png")
            assert preview.content.startswith(b"\x89PNG")

    asyncio.run(exercise())


def test_demo_api_rejects_an_unsupported_task_instead_of_reusing_hero_evidence():
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://linecard.test") as client:
            response = await client.post("/api/demo/retrieve", json={"task": "Weekly lubrication"})
            assert response.status_code == 422
            assert "infeed" in response.json()["detail"].lower()

    asyncio.run(exercise())


def test_demo_api_runs_the_actual_400_page_scale_fixture_without_unlocking_export():
    async def exercise() -> None:
        transport = httpx.ASGITransport(app=create_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://linecard.test") as client:
            result = await client.post("/api/demo/scale")
            assert result.status_code == 200
            payload = result.json()
            assert payload["page_count"] == 400
            assert len(payload["sha256"]) == 64
            assert payload["retrieval_hits"] > 0
            assert payload["card_eligibility"] == "BLOCKED_SCALE_PROOF_ONLY"
            manual = await client.get(payload["manual_url"])
            assert manual.status_code == 200
            assert len(fitz.open(stream=manual.content, filetype="pdf")) == 400

    asyncio.run(exercise())
