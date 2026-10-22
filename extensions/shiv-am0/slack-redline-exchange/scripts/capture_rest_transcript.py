#!/usr/bin/env python3
"""Drive a whole negotiation over the REST surface and record every call.

This exists to answer one question with evidence rather than prose: can a machine run
this end to end, with no human clicking anything in Slack? It runs against the built-in
fake, so it needs no key and no network, and it writes a transcript of the real request
and response bodies rather than a description of them.

    uv run python scripts/capture_rest_transcript.py > docs/rest-transcript.md
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from conftest import CAP_INSTRUCTION, make_contract_docx, make_settings  # noqa: E402
from redline.core.negotiation import NegotiationService  # noqa: E402
from redline.core.store import Store  # noqa: E402
from redline.main import create_app  # noqa: E402
from redline.slack.simulator import InMemoryMessenger  # noqa: E402
from redline.superdocs.client import SuperDocsClient  # noqa: E402
from redline.superdocs.fake import FakeSuperDocs  # noqa: E402


def show(title: str, method: str, path: str, request, response) -> None:
    print(f"\n### {title}\n")
    print(f"`{method} {path}` -> **{response.status_code}**\n")
    if request is not None:
        print("Request")
        print("```json")
        print(json.dumps(request, indent=2)[:1400])
        print("```\n")
    print("Response")
    print("```json")
    body = response.json()
    print(json.dumps(body, indent=2)[:1800])
    print("```")


async def main(tmp: Path) -> None:
    settings = make_settings(tmp)
    store = Store(settings.database_path)
    service = NegotiationService(
        settings, store, SuperDocsClient(FakeSuperDocs()), InMemoryMessenger()
    )
    app = create_app(service)

    print("# REST transcript — a full negotiation, no human in Slack")
    print()
    print("Captured by `scripts/capture_rest_transcript.py` against the built-in fake:")
    print("no API key, no network. Every body below is verbatim.")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        async with app.router.lifespan_context(app):
            resp = await client.post(
                "/deals/upload",
                data={"name": "Acme-Globex MSA", "side": "vendor", "user": "U_VENDOR"},
                files={
                    "file": (
                        "MSA.docx",
                        make_contract_docx(),
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document",
                    )
                },
            )
            show("1. Open a deal (multipart upload)", "POST", "/deals/upload", None, resp)
            deal_id = resp.json()["deal_id"]

            payload = {
                "side": "vendor",
                "user": "U_VENDOR",
                "instruction": CAP_INSTRUCTION,
                "source_channel_id": settings.shared_channel,
            }
            resp = await client.post(f"/deals/{deal_id}/propose", json=payload)
            show("2. Propose an edit", "POST", f"/deals/{deal_id}/propose", payload, resp)
            proposals = resp.json()["proposals"]

            resp = await client.post(f"/deals/{deal_id}/propose", json=payload)
            show(
                "3. Propose the identical edit again (idempotency)",
                "POST",
                f"/deals/{deal_id}/propose",
                payload,
                resp,
            )
            print(
                "\n> Same `job_id` as call 2. The repeat folded into the existing job "
                "instead of starting a second one and billing a second operation."
            )

            proposal_id = proposals[0]["id"]
            for side, user in (("vendor", "U_VENDOR"), ("customer", "U_CUSTOMER")):
                body = {"side": side, "user": user, "approved": True}
                resp = await client.post(
                    f"/deals/{deal_id}/proposals/{proposal_id}/decide", json=body
                )
                show(
                    f"{4 if side == 'vendor' else 5}. Approve as {side}",
                    "POST",
                    f"/deals/{deal_id}/proposals/{proposal_id}/decide",
                    body,
                    resp,
                )
            print(
                "\n> Under `dual_consent` the change commits only after the second "
                "approval. One side alone is recorded but does not commit."
            )

            resp = await client.get(f"/deals/{deal_id}/status")
            show("6. Status", "GET", f"/deals/{deal_id}/status", None, resp)

            resp = await client.get(f"/deals/{deal_id}/history")
            show("7. Audit trail", "GET", f"/deals/{deal_id}/history", None, resp)

    print("\n---\n")
    print("Seven calls, no Slack, no key. The same `NegotiationService` backs both the")
    print("Slack app and this surface, so the rules proved here are the rules in Slack.")


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(main(Path(tmp)))
