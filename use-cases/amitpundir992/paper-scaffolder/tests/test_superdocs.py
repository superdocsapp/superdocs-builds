from __future__ import annotations

import json
import unittest
from unittest.mock import Mock

from paper_scaffolder.http_transport import (
    HttpRequest,
    HttpResponse,
    TransportNetworkError,
    TransportTimeoutError,
)
from paper_scaffolder.superdocs import (
    SuperDocsAuthenticationError,
    SuperDocsHttpAdapter,
    SuperDocsMalformedResponseError,
    SuperDocsNetworkError,
    SuperDocsRequestError,
    SuperDocsSettings,
    SuperDocsTimeoutError,
)
from paper_scaffolder.superdocs_workflow import (
    DecisionConflictError,
    SuperDocsWorkflowService,
)


def json_response(status: int, value: object) -> HttpResponse:
    return HttpResponse(
        status_code=status,
        headers={"content-type": "application/json"},
        body=json.dumps(value).encode("utf-8"),
    )


class FakeTransport:
    def __init__(self, *results: HttpResponse | Exception) -> None:
        self.results = list(results)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def upload_payload() -> dict[str, object]:
    return {
        "html": '<h1 data-chunk-id="title">Paper</h1>',
        "session_id": "paper-session",
        "filename": "paper.html",
        "chunks_count": 1,
        "version_id": "version-1",
    }


def job_payload(*, pending_changes: object | None = None) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if pending_changes is not None:
        metadata["pending_changes"] = pending_changes
    return {
        "job_id": "job-1",
        "session_id": "paper-session",
        "job_type": "chat",
        "status": "awaiting_approval" if pending_changes is not None else "in_progress",
        "created_at": "2026-08-10T00:00:00Z",
        "updated_at": "2026-08-10T00:00:01Z",
        "progress": 50,
        "result": None,
        "error": None,
        "metadata": metadata,
    }


CHANGE = {
    "change_id": "change-1",
    "operation": "edit",
    "chunk_id": "methods",
    "document_id": None,
    "old_html": "<h2>Methods</h2>",
    "new_html": "<h2>Methodology</h2>",
    "ai_explanation": "Adjusted the heading to the requested journal style.",
}


class SuperDocsHttpAdapterTests(unittest.TestCase):
    def adapter(self, transport: FakeTransport) -> SuperDocsHttpAdapter:
        return SuperDocsHttpAdapter(
            SuperDocsSettings(
                api_key="sk_test_only",
                base_url="https://superdocs.test",
                timeout_seconds=2,
            ),
            transport,
        )

    def test_upload_success(self) -> None:
        transport = FakeTransport(json_response(200, upload_payload()))

        result = self.adapter(transport).upload_document(
            filename="paper.html",
            content=b"<h1>Paper</h1>",
            session_id="paper-session",
        )

        self.assertEqual(result.session_id, "paper-session")
        self.assertEqual(result.chunks_count, 1)
        request = transport.requests[0]
        self.assertEqual(request.url, "https://superdocs.test/v1/documents/upload")
        self.assertTrue(request.headers["Content-Type"].startswith("multipart/form-data"))
        self.assertIn(b'name="session_id"', request.body or b"")
        self.assertIn(b"paper-session", request.body or b"")
        self.assertEqual(request.headers["Authorization"], "Bearer sk_test_only")

    def test_upload_failure(self) -> None:
        adapter = self.adapter(FakeTransport(json_response(500, {"detail": "failed"})))

        with self.assertRaises(SuperDocsRequestError):
            adapter.upload_document(
                filename="paper.html",
                content=b"<h1>Paper</h1>",
                session_id="paper-session",
            )

    def test_edit_request_success_uses_human_review(self) -> None:
        transport = FakeTransport(
            json_response(
                200,
                {
                    "job_id": "job-1",
                    "session_id": "paper-session",
                    "status": "pending",
                    "message": "queued",
                },
            )
        )

        result = self.adapter(transport).send_edit_instruction(
            session_id="paper-session",
            document_html="<h2>Methods</h2>",
            instruction="Format Methods for the journal.",
        )

        self.assertEqual(result.job_id, "job-1")
        request_body = json.loads((transport.requests[0].body or b"").decode())
        self.assertEqual(request_body["approval_mode"], "ask_every_time")
        self.assertEqual(request_body["response_mode"], "full")

    def test_edit_after_upload_can_reuse_session_document(self) -> None:
        transport = FakeTransport(
            json_response(
                202,
                {
                    "job_id": "job-1",
                    "session_id": "paper-session",
                    "status": "pending",
                    "message": "queued",
                },
            )
        )

        self.adapter(transport).send_edit_instruction(
            session_id="paper-session",
            instruction="Format Methods for the journal.",
        )

        request_body = json.loads((transport.requests[0].body or b"").decode())
        self.assertNotIn("document_html", request_body)

    def test_proposed_change_retrieval(self) -> None:
        adapter = self.adapter(FakeTransport(json_response(200, job_payload(pending_changes=[CHANGE]))))

        changes = adapter.get_proposed_changes(job_id="job-1")

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].change_id, "change-1")
        self.assertEqual(changes[0].old_html, "<h2>Methods</h2>")

    def test_json_encoded_proposed_change_is_parsed_twice(self) -> None:
        encoded_change = json.dumps(json.dumps(CHANGE))
        encoded_list = json.dumps([encoded_change])
        adapter = self.adapter(
            FakeTransport(json_response(200, job_payload(pending_changes=encoded_list)))
        )

        changes = adapter.get_proposed_changes(job_id="job-1")

        self.assertEqual(changes[0].new_html, "<h2>Methodology</h2>")

    def test_approve_one_change(self) -> None:
        transport = FakeTransport(json_response(200, {"status": "accepted"}))

        self.adapter(transport).approve_change(
            session_id="paper-session", job_id="job-1", change_id="change-1"
        )

        payload = json.loads((transport.requests[0].body or b"").decode())
        self.assertEqual(
            payload,
            {"job_id": "job-1", "change_id": "change-1", "approved": True},
        )

    def test_reject_one_change(self) -> None:
        transport = FakeTransport(json_response(200, {"status": "accepted"}))

        self.adapter(transport).reject_change(
            session_id="paper-session",
            job_id="job-1",
            change_id="change-1",
            feedback="Keep the original heading.",
        )

        payload = json.loads((transport.requests[0].body or b"").decode())
        self.assertFalse(payload["approved"])
        self.assertEqual(payload["feedback"], "Keep the original heading.")

    def test_export_success(self) -> None:
        transport = FakeTransport(
            HttpResponse(
                200,
                {
                    "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "content-disposition": 'attachment; filename="paper.docx"',
                },
                b"docx-bytes",
            )
        )

        result = self.adapter(transport).export_document(
            session_id="paper-session", file_format="docx", filename="paper"
        )

        self.assertEqual(result.content, b"docx-bytes")
        self.assertEqual(result.filename, "paper.docx")

    def test_authentication_failure(self) -> None:
        adapter = self.adapter(FakeTransport(json_response(401, {"detail": "no"})))

        with self.assertRaises(SuperDocsAuthenticationError):
            adapter.get_job(job_id="job-1")

    def test_malformed_external_response(self) -> None:
        adapter = self.adapter(FakeTransport(HttpResponse(200, {}, b"not-json")))

        with self.assertRaises(SuperDocsMalformedResponseError):
            adapter.send_edit_instruction(
                session_id="paper-session",
                document_html="<h2>Methods</h2>",
                instruction="Format Methods.",
            )

    def test_timeout_failure(self) -> None:
        adapter = self.adapter(FakeTransport(TransportTimeoutError("timeout")))

        with self.assertRaises(SuperDocsTimeoutError):
            adapter.get_job(job_id="job-1")

    def test_network_failure(self) -> None:
        adapter = self.adapter(FakeTransport(TransportNetworkError("offline")))

        with self.assertRaises(SuperDocsNetworkError):
            adapter.get_job(job_id="job-1")


class SuperDocsWorkflowTests(unittest.TestCase):
    def test_same_decision_is_idempotent(self) -> None:
        adapter = Mock()
        adapter.approve_change.return_value = {"status": "accepted"}
        workflow = SuperDocsWorkflowService(adapter)

        first = workflow.decide_change(
            session_id="session", job_id="job", change_id="change", approved=True
        )
        second = workflow.decide_change(
            session_id="session", job_id="job", change_id="change", approved=True
        )

        self.assertFalse(first.idempotent_replay)
        self.assertTrue(second.idempotent_replay)
        adapter.approve_change.assert_called_once()

    def test_conflicting_replay_is_rejected(self) -> None:
        adapter = Mock()
        adapter.approve_change.return_value = {"status": "accepted"}
        workflow = SuperDocsWorkflowService(adapter)
        workflow.decide_change(
            session_id="session", job_id="job", change_id="change", approved=True
        )

        with self.assertRaises(DecisionConflictError):
            workflow.decide_change(
                session_id="session",
                job_id="job",
                change_id="change",
                approved=False,
            )


if __name__ == "__main__":
    unittest.main()
