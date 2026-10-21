import asyncio
import json
import unittest

import httpx

from app import SuperDocsApi


class SuperDocsContractTests(unittest.TestCase):
    def test_intake_uses_document_upload_then_approval_gated_chat(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if request.url.path == "/v1/sessions/init":
                return httpx.Response(200, json={"session_id": json.loads(request.content)["session_id"]})
            if request.url.path == "/v1/uploads":
                return httpx.Response(200, json={"upload_id": "upload-1", "upload_url": "https://signed.example/upload"})
            if request.url.host == "signed.example":
                return httpx.Response(200)
            if request.url.path == "/v1/uploads/upload-1/process":
                return httpx.Response(200, json={"status": "processed"})
            if request.url.path.endswith("/documents"):
                return httpx.Response(200, json={"documents": [{"document_id": "document-1", "html": "<p>Source</p>"}]})
            if request.url.path == "/v1/chat/async":
                return httpx.Response(200, json={"job_id": "job-1"})
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")

        async def exercise():
            transport = httpx.MockTransport(handler)
            async with httpx.AsyncClient(base_url="https://api.superdocs.app", headers={"Authorization": "Bearer test-key"}, transport=transport) as client:
                api = SuperDocsApi("test-key", client=client, upload_transport=transport)
                session_id, document_id, job_id = await api.intake("manual.pdf", "application/pdf", b"synthetic document", "Make it clearer.")
                self.assertEqual((document_id, job_id), ("document-1", "job-1"))
                self.assertEqual(len(session_id), 36)

        asyncio.run(exercise())
        chat = next(call for call in calls if call.url.path == "/v1/chat/async")
        self.assertEqual(json.loads(chat.content)["approval_mode"], "ask_every_time")
        signed_upload = next(call for call in calls if call.url.host == "signed.example")
        self.assertIsNone(signed_upload.headers.get("authorization"))


if __name__ == "__main__":
    unittest.main()
