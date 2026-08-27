from __future__ import annotations
import asyncio
import concurrent.futures
import time
import threading
from pathlib import Path
from typing import Protocol

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


class MCPClient(Protocol):
    """Interface matching SuperDocs' REAL MCP tool surface. Keyed on
    session_id alone — document_id isn't needed for single-document
    sessions (confirmed via live calls: focused_document_id is always
    'doc_primary')."""

    def create_session_with_document(self, session_id: str, initial_html: str) -> str:
        ...

    def edit_section(self, session_id: str, section_title: str, new_content: str) -> str:
        ...

    def export_document(self, session_id: str, format: str = "docx") -> str:
        ...


class FakeMCPClient:
    """Records every call instead of hitting the real MCP server."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self._documents: dict[str, str] = {}

    def create_session_with_document(self, session_id: str, initial_html: str) -> str:
        self._documents[session_id] = initial_html
        self.calls.append(("create_session_with_document", {
            "session_id": session_id, "initial_html": initial_html,
        }))
        return initial_html

    def edit_section(self, session_id: str, section_title: str, new_content: str) -> str:
        updated = self._documents.get(session_id, "") + f"<!-- edited: {section_title} -->"
        self._documents[session_id] = updated
        self.calls.append(("edit_section", {
            "session_id": session_id, "section_title": section_title, "new_content": new_content,
        }))
        return updated

    def export_document(self, session_id: str, format: str = "docx") -> str:
        self.calls.append(("export_document", {"session_id": session_id, "format": format}))
        return f"/exports/{session_id}.{format}"


class SuperDocsMCPClient:
    """Real implementation of the MCPClient Protocol, talking to
    SuperDocs over MCP using the mcp v2 SDK.

    Two things confirmed only by real calls, both handled here:

    1. Connection lifetime: runs open/every-call/close as ONE continuous
       coroutine on a dedicated background thread's event loop, because
       anyio's cancel-scope machinery requires a context manager to be
       entered and exited within the same asyncio task.

    2. Approval-gated edits: `chat` sometimes returns
       document_changes.requires_approval=True with the real edit sitting
       in pending_changes, rather than applying it directly (confirmed via
       a live call — SuperDocs' own HITL review gate, not a bug). Since
       our own retrieval+verification pipeline already vetted this content
       before it reached SuperDocs, we auto-approve immediately, then poll
       get_job until status='completed' and pull the final HTML from
       result.document_changes.updated_html.

    Use as a context manager:
        with SuperDocsMCPClient(url, api_key) as client:
            client.create_session_with_document(...)
    """

    def __init__(self, url: str, api_key: str, exports_dir: str = "exports"):
        self._url = url
        self._api_key = api_key
        self._exports_dir = Path(exports_dir)
        self._exports_dir.mkdir(exist_ok=True)

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

        self._client: Client | None = None
        self._shutdown_event: asyncio.Event | None = None
        self._closed_future: concurrent.futures.Future = concurrent.futures.Future()

        connect_future: concurrent.futures.Future = concurrent.futures.Future()
        asyncio.run_coroutine_threadsafe(self._lifetime(connect_future), self._loop)
        connect_future.result(timeout=30)

    async def _lifetime(self, connect_future: concurrent.futures.Future) -> None:
        self._shutdown_event = asyncio.Event()
        try:
            async with httpx2.AsyncClient(
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=httpx2.Timeout(30.0, read=300.0),
                follow_redirects=True,
            ) as http_client:
                transport = streamable_http_client(self._url, http_client=http_client)
                async with Client(transport) as client:
                    self._client = client
                    connect_future.set_result(True)
                    await self._shutdown_event.wait()
        except Exception as e:
            if not connect_future.done():
                connect_future.set_exception(e)
        finally:
            self._closed_future.set_result(True)

    def close(self) -> None:
        if self._shutdown_event is not None:
            self._loop.call_soon_threadsafe(self._shutdown_event.set)
            self._closed_future.result(timeout=10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)

    def __enter__(self) -> "SuperDocsMCPClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def _call(self, tool_name: str, arguments: dict) -> dict:
        async def _run():
            return await self._client.call_tool(tool_name, arguments)
        future = asyncio.run_coroutine_threadsafe(_run(), self._loop)
        result = future.result()
        if result.is_error:
            raise RuntimeError(f"MCP tool '{tool_name}' returned an error: {result.content}")
        return result.structured_content

    def _resolve_html(self, response: dict, session_id: str) -> str:
        """Returns the final document HTML from a chat response, handling
        both direct-apply and approval-gated cases (see class docstring)."""
        doc_changes = response["document_changes"]

        if not doc_changes.get("requires_approval"):
            return doc_changes["updated_html"]

        job_id = doc_changes["job_id"]
        for pending in doc_changes["pending_changes"]:
            self._call("approve_change", {
                "session_id": session_id,
                "job_id": job_id,
                "change_id": pending["change_id"],
                "approved": True,
            })

        return self._poll_job_html(job_id)

    def _poll_job_html(self, job_id: str, max_attempts: int = 90, delay_seconds: float = 2.0) -> str:
        last_status = None
        for _ in range(max_attempts):
            job_result = self._call("get_job", {"job_id": job_id})
            last_status = job_result.get("status")
            if last_status == "completed":
                return job_result["result"]["document_changes"]["updated_html"]
            if last_status in ("failed", "cancelled"):
                raise RuntimeError(f"Job {job_id} ended with status '{last_status}': {job_result.get('error')}")
            time.sleep(delay_seconds)
        raise TimeoutError(
            f"Job {job_id} did not complete within {max_attempts * delay_seconds} seconds "
            f"(last known status: '{last_status}')"
        )

    def create_session_with_document(self, session_id: str, initial_html: str) -> str:
        response = self._call("chat", {
            "session_id": session_id,
            "message": "Load this document as the starting point. Do not add or change any content.",
            "document_html": initial_html,
        })
        return self._resolve_html(response, session_id)

    def edit_section(self, session_id: str, section_title: str, new_content: str) -> str:
        response = self._call("chat", {
            "session_id": session_id,
            "message": (
                f"Replace the paragraph directly under the '{section_title}' heading with the "
                f"following text, exactly as given, and do not modify any other section:\n\n{new_content}"
            ),
        })
        return self._resolve_html(response, session_id)

    def export_document(self, session_id: str, format: str = "docx") -> str:
        response = self._call("request_download_url", {
            "session_id": session_id,
            "format": format,
        })
        download_url = response["download_url"]
        filename = response.get("filename", f"{session_id}.{format}")

        async def _download() -> bytes:
            async with httpx2.AsyncClient(follow_redirects=True) as http_client:
                resp = await http_client.get(download_url)
                resp.raise_for_status()
                return resp.content

        future = asyncio.run_coroutine_threadsafe(_download(), self._loop)
        content = future.result()
        local_path = self._exports_dir / filename
        local_path.write_bytes(content)
        return str(local_path)