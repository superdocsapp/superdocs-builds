from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from superdocs_sdk import (
    AsyncSuperDocsClient,
    AuthenticationError,
    RateLimitError,
    SuperDocsClient,
)
from superdocs_sdk.transport import Response

SSE_LINES = [
    ": keep-alive",
    "event: proposed_change_batch",
    'data: {"content":"{\\"type\\":\\"proposed_change_batch\\",\\"batch_id\\":\\"b1\\",\\"batch_total\\":1,\\"changes\\":[{\\"change_id\\":\\"c1\\",\\"operation\\":\\"replace\\",\\"chunk_id\\":\\"a\\"}]}"}',
    "",
]


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.put_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []
        self.fail_once = False
        self.closed = False

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        files: Any | None = None,
        data: Any | None = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Response:
        self.calls.append(
            {
                "method": method,
                "path": path,
                "json": json_body,
                "files": files,
                "data": data,
                "content": content,
                "headers": headers or {},
                "timeout": timeout,
            }
        )
        if self.fail_once:
            self.fail_once = False
            return Response(
                503,
                {"x-request-id": "r1", "retry-after": "0.1"},
                b'{"code":"busy","message":"try later"}',
            )
        if path == "/v1/chat":
            return Response(
                200,
                {},
                b'{"response":"ok","document_changes":{"updated_html":"<p data-chunk-id=\\"a\\">ok</p>"}}',
            )
        if path == "/v1/chat/async":
            return Response(200, {}, b'{"job_id":"j1","session_id":"s1"}')
        if path == "/v1/jobs/j1":
            return Response(200, {}, b'{"job_id":"j1","session_id":"s1","status":"awaiting_approval"}')
        if path == "/v1/sessions/init":
            return Response(200, {}, b'{"session_id":"s1"}')
        if path.startswith("/v1/sessions"):
            return Response(200, {}, b'{"items":[{"id":"s1"}],"next_cursor":null}')
        if path.startswith("/v1/documents/export"):
            return Response(
                200,
                {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                b"DOCX",
            )
        if path == "/v1/documents/upload":
            return Response(
                200,
                {},
                b'{"filename":"small.md","chunks_count":1,"html":"<p data-chunk-id=\\"a\\">x</p>"}',
            )
        if path == "/v1/uploads":
            return Response(
                200,
                {},
                b'{"upload_id":"up_1","upload_url":"https://storage.invalid/put"}',
            )
        if path == "/v1/uploads/up_1/process":
            return Response(200, {}, b'{"chunks_count":2,"version_id":"v1"}')
        if path == "/v1/documents":
            return Response(200, {}, b'{"items":[{"id":"d1","filename":"deal.docx"}]}')
        return Response(200, {}, b"{}")

    def stream_lines(
        self, path: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> Any:
        self.stream_calls.append({"path": path, "headers": headers or {}, "timeout": timeout})
        return iter(SSE_LINES)

    def put_bytes(
        self, url: str, content: bytes, *, headers: dict[str, str], timeout: float | None = None
    ) -> Response:
        self.put_calls.append(
            {"url": url, "content": content, "headers": headers, "timeout": timeout}
        )
        return Response(200, {}, b"")

    def close(self) -> None:
        self.closed = True


class FakeAsyncTransport:
    def __init__(self) -> None:
        self.sync = FakeTransport()

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.sync.calls

    @property
    def put_calls(self) -> list[dict[str, Any]]:
        return self.sync.put_calls

    @property
    def stream_calls(self) -> list[dict[str, Any]]:
        return self.sync.stream_calls

    @property
    def fail_once(self) -> bool:
        return self.sync.fail_once

    @fail_once.setter
    def fail_once(self, value: bool) -> None:
        self.sync.fail_once = value

    async def request(self, *args: Any, **kwargs: Any) -> Response:
        return self.sync.request(*args, **kwargs)

    async def stream_lines(self, path: str, **kwargs: Any) -> Any:
        self.sync.stream_calls.append({"path": path, **kwargs})
        for line in SSE_LINES:
            yield line

    async def put_bytes(self, *args: Any, **kwargs: Any) -> Response:
        return self.sync.put_bytes(*args, **kwargs)

    async def close(self) -> None:
        self.sync.closed = True


def normalized_calls(calls: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (call["method"], call["path"], call["json"], call["headers"], call["timeout"])
        for call in calls
    ]


class SdkTests(unittest.TestCase):
    def test_sync_async_share_request_contract(self) -> None:
        sync_transport = FakeTransport()
        sync = SuperDocsClient(
            api_key="sk_test",
            transport=sync_transport,
            timeout=17,
            idempotency_key_factory=lambda: "idem-1",
        )
        sync.chat(session_id="s1", message="edit", document_html="<p>x</p>")
        list(sync.iter_sessions())
        sync.export_document(session_id="s1")

        async def run() -> list[dict[str, Any]]:
            transport = FakeAsyncTransport()
            client = AsyncSuperDocsClient(
                api_key="sk_test",
                transport=transport,
                timeout=17,
                idempotency_key_factory=lambda: "idem-1",
            )
            await client.chat(session_id="s1", message="edit", document_html="<p>x</p>")
            _ = [session async for session in client.iter_sessions()]
            await client.export_document(session_id="s1")
            return transport.calls

        self.assertEqual(normalized_calls(sync_transport.calls), normalized_calls(asyncio.run(run())))
        self.assertNotIn("sk_test", repr(sync))

    def test_retry_reuses_idempotency_key(self) -> None:
        transport = FakeTransport()
        transport.fail_once = True
        client = SuperDocsClient(api_key="sk_test", transport=transport)
        self.assertEqual(
            "ok", client.chat(session_id="s1", message="edit", idempotency_key="fixed").response
        )
        self.assertEqual(["fixed", "fixed"], [c["headers"]["Idempotency-Key"] for c in transport.calls])

    def test_non_retryable_error_has_specific_type_and_action(self) -> None:
        class BadTransport(FakeTransport):
            def request(self, *args: Any, **kwargs: Any) -> Response:
                return Response(401, {"x-request-id": "req"}, b'{"code":"bad_key","message":"No"}')

        with self.assertRaises(AuthenticationError) as caught:
            SuperDocsClient(api_key="sk_test", transport=BadTransport()).chat(
                session_id="s1", message="edit"
            )
        self.assertEqual("bad_key", caught.exception.code)
        self.assertEqual("req", caught.exception.request_id)
        self.assertIn("API_KEY", caught.exception.suggested_action or "")

    def test_rate_limit_exposes_retry_after(self) -> None:
        class LimitedTransport(FakeTransport):
            def request(self, *args: Any, **kwargs: Any) -> Response:
                return Response(429, {"retry-after": "3.5"}, b'{"code":"limited"}')

        with self.assertRaises(RateLimitError) as caught:
            SuperDocsClient(api_key="sk_test", transport=LimitedTransport(), retries=0).chat(
                session_id="s1", message="edit"
            )
        self.assertEqual(3.5, caught.exception.retry_after)

    def test_upload_strategy_puts_and_processes_large_file_without_auth_leak(self) -> None:
        transport = FakeTransport()
        client = SuperDocsClient(api_key="sk_test", transport=transport)
        with tempfile.TemporaryDirectory() as tmp:
            small = Path(tmp) / "small.md"
            small.write_text("x", encoding="utf-8")
            large = Path(tmp) / "large.md"
            large.write_text("x" * 100_001, encoding="utf-8")
            self.assertEqual("small.md", client.upload_document(small, session_id="s1").filename)
            result = client.upload_document(large, session_id="s1")
        self.assertEqual("up_1", result.upload_id)
        self.assertEqual(100_001, len(transport.put_calls[0]["content"]))
        self.assertNotIn("Authorization", transport.put_calls[0]["headers"])
        self.assertEqual(
            ["/v1/uploads", "/v1/uploads/up_1/process"],
            [c["path"] for c in transport.calls if c["path"].startswith("/v1/uploads")],
        )

    def test_progress_is_streamed_and_api_key_never_enters_url(self) -> None:
        transport = FakeTransport()
        client = SuperDocsClient(api_key="sk_test", transport=transport)
        event = next(client.progress("j1", "s1"))
        batch = client.parse_change_batch(event)
        self.assertEqual("c1", batch.changes[0].change_id)
        self.assertEqual("/v1/chat/s1/stream?job_id=j1", transport.stream_calls[0]["path"])
        self.assertNotIn("sk_test", transport.stream_calls[0]["path"])

    def test_wait_returns_for_human_input(self) -> None:
        job = SuperDocsClient(api_key="sk_test", transport=FakeTransport()).wait(
            "j1", poll_interval_s=0, timeout_s=1
        )
        self.assertTrue(job.needs_input)

    def test_per_call_timeout_and_context_cleanup(self) -> None:
        transport = FakeTransport()
        with SuperDocsClient(api_key="sk_test", transport=transport) as client:
            client.chat(session_id="s1", message="edit", timeout=4.25)
        self.assertEqual(4.25, transport.calls[0]["timeout"])
        self.assertTrue(transport.closed)

    def test_async_retry_does_not_block_event_loop(self) -> None:
        async def run() -> bool:
            transport = FakeAsyncTransport()
            transport.fail_once = True
            client = AsyncSuperDocsClient(api_key="sk_test", transport=transport)
            task = asyncio.create_task(client.chat(session_id="s1", message="edit"))
            await asyncio.sleep(0.02)
            yielded_while_retry_waited = not task.done()
            await task
            return yielded_while_retry_waited

        self.assertTrue(asyncio.run(run()))

    def test_async_progress_and_large_upload_parity(self) -> None:
        async def run() -> tuple[str, str, bool]:
            transport = FakeAsyncTransport()
            client = AsyncSuperDocsClient(api_key="sk_test", transport=transport)
            async for event in client.progress("j1", "s1"):
                change_id = client.parse_change_batch(event).changes[0].change_id
                break
            with tempfile.TemporaryDirectory() as tmp:
                large = Path(tmp) / "large.md"
                large.write_text("x" * 100_001, encoding="utf-8")
                upload_id = (await client.upload_document(large, session_id="s1")).upload_id
            leaked = "Authorization" in transport.put_calls[0]["headers"]
            return change_id, upload_id or "", leaked

        self.assertEqual(("c1", "up_1", False), asyncio.run(run()))

    def test_export_requires_exactly_one_source(self) -> None:
        client = SuperDocsClient(api_key="sk_test", transport=FakeTransport())
        with self.assertRaises(ValueError):
            client.export_document()
        with self.assertRaises(ValueError):
            client.export_document(session_id="s1", html="<p>x</p>")


if __name__ == "__main__":
    unittest.main()
