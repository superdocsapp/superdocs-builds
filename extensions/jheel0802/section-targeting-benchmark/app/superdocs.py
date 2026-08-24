from __future__ import annotations

import base64
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from typing import Any, Protocol
from zipfile import ZipFile

import httpx

from .config import Settings
from .document_evidence import parse_document_html


class SuperDocsError(RuntimeError):
    pass


@dataclass
class RunResult:
    status: str
    session_id: str
    textual_response: str | None
    evidence: dict[str, Any]
    raw: dict[str, Any]
    latency_ms: float
    operations_charged: int = 0
    job_id: str | None = None
    error: str | None = None


class SuperDocsClient(Protocol):
    def run(self, case: dict[str, Any], document: dict[str, Any]) -> RunResult: ...
    def decide_changes(self, session_id: str, job_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]: ...
    def get_job(self, job_id: str) -> dict[str, Any]: ...
    def poll_after_approval(self, job_id: str, approved_change_ids: list[str] | None = None) -> dict[str, Any]: ...
    def list_session_documents(self, session_id: str) -> dict[str, Any]: ...
    def export(self, session_id: str, format: str = "docx") -> tuple[bytes, str]: ...


def parse_json_strings(value: Any) -> Any:
    """Decode JSON-encoded API fields while preserving ordinary text."""
    if isinstance(value, dict):
        return {k: parse_json_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [parse_json_strings(v) for v in value]
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            return parse_json_strings(json.loads(value))
        except json.JSONDecodeError:
            return value
    return value


def _normalized_text(value: str) -> str:
    return " ".join(html.unescape(value).split())


class _HtmlNode:
    def __init__(self, tag: str="root", attrs: dict[str,str]|None=None):
        self.tag, self.attrs, self.children = tag.lower(), attrs or {}, []

    def text(self) -> str:
        return _normalized_text("".join(child if isinstance(child,str) else child.text() for child in self.children))


class _ChunkHtmlParser(HTMLParser):
    VOID={"area","base","br","col","embed","hr","img","input","link","meta","param","source","track","wbr"}
    def __init__(self):
        super().__init__(convert_charrefs=True); self.root=_HtmlNode(); self.stack=[self.root]
    def handle_starttag(self, tag: str, attrs: list[tuple[str,str|None]]) -> None:
        node=_HtmlNode(tag,{key:value or "" for key,value in attrs}); self.stack[-1].children.append(node)
        if tag.lower() not in self.VOID: self.stack.append(node)
    def handle_startendtag(self, tag: str, attrs: list[tuple[str,str|None]]) -> None: self.handle_starttag(tag,attrs)
    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack)-1,0,-1):
            if self.stack[index].tag==tag.lower(): del self.stack[index:]; break
    def handle_data(self, data: str) -> None: self.stack[-1].children.append(data)


def _docx_paragraph_paths(content: bytes) -> list[tuple[str,str|None]]:
    """Return paragraph text and its real Word heading ancestry in document order."""
    try:
        with ZipFile(BytesIO(content)) as archive: root=ET.fromstring(archive.read("word/document.xml"))
    except (KeyError,ValueError,ET.ParseError): return []
    ns="{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"; headings: dict[int,str]={}; rows=[]
    for paragraph in root.iter(ns+"p"):
        text_value=_normalized_text("".join(node.text or "" for node in paragraph.iter(ns+"t")))
        if not text_value: continue
        style=paragraph.find("./"+ns+"pPr/"+ns+"pStyle"); style_id=style.get(ns+"val","") if style is not None else ""
        match=re.fullmatch(r"Heading\s*([1-6])",style_id,re.I)
        if match:
            level=int(match.group(1)); headings[level]=text_value
            for stale in [key for key in headings if key>level]: headings.pop(stale)
        path=" > ".join(headings[key] for key in sorted(headings)) or None
        rows.append((text_value,path))
    return rows


def build_chunk_heading_map(document_html: str|None, source_content: bytes|None=None, filename: str|None=None) -> dict[str,str]:
    """Resolve official chunk IDs to explicit heading ancestry; unresolved IDs are omitted."""
    structure=parse_document_html(document_html); mapping=dict(structure.chunk_paths)
    if source_content and (filename or "").lower().endswith(".docx"):
        source_rows=_docx_paragraph_paths(source_content); cursor=0
        for chunk in structure.chunks:
            if chunk.chunk_id in mapping: continue
            text_value=structure.nodes_by_chunk[chunk.chunk_id].text()
            if not text_value: continue
            for index in range(cursor,len(source_rows)):
                if source_rows[index][0]==text_value:
                    if source_rows[index][1]: mapping[chunk.chunk_id]=source_rows[index][1]
                    cursor=index+1; break
    return mapping


def resolve_pending_changes(changes: list[dict[str,Any]], chunk_heading_paths: dict[str,str]) -> list[dict[str,Any]]:
    resolved=[]
    for original in changes:
        change=dict(original)
        placement_id=change.get("insert_after_chunk_id") if change.get("operation")=="create" else change.get("chunk_id")
        change["resolved_section_path"]=chunk_heading_paths.get(placement_id) if placement_id else None
        if change.get("operation")=="create" and not placement_id:
            change["proposal_placement_unavailable"]=True
        resolved.append(change)
    return resolved


class RealSuperDocsClient:
    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise SuperDocsError("SUPERDOCS_API_KEY is missing. Copy .env.example to .env and add your key.")
        self.settings = settings
        self.http = httpx.Client(
            base_url=settings.base_url,
            headers={"Authorization": f"Bearer {settings.api_key}", "Content-Type": "application/json"},
            timeout=httpx.Timeout(60, read=max(60, settings.poll_timeout_seconds)),
        )

    def _json(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise SuperDocsError(f"SuperDocs request failed: {exc}") from exc
        if response.is_error:
            content_type = response.headers.get("content-type", "")
            detail = response.json() if "json" in content_type else response.text[:1000]
            raise SuperDocsError(f"SuperDocs HTTP {response.status_code}: {detail}")
        try:
            return parse_json_strings(response.json())
        except ValueError as exc:
            raise SuperDocsError("SuperDocs returned a non-JSON response where JSON was required.") from exc

    def _upload(self, session_id: str, document: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "filename": document["filename"],
            "file_base64": base64.b64encode(document["content"]).decode(),
            "session_id": session_id,
            "return_html": True,
        }
        return self._json("POST", "/v1/documents/upload-base64", json=payload)

    def run(self, case: dict[str, Any], document: dict[str, Any]) -> RunResult:
        started = time.perf_counter()
        session_id = f"benchmark_case_{case['id']}_{int(time.time() * 1000)}"
        upload = self._upload(session_id, document)
        chunk_heading_paths=build_chunk_heading_map(upload.get("html"),document.get("content"),document.get("filename"))
        common = {
            "message": case["instruction"],
            "session_id": session_id,
            "response_mode": "compact",
            "cross_session_memory": False,
            "cross_session_search": False,
        }
        # Chat is a combined analyze/edit endpoint. Even benchmark questions use
        # the approval-gated async flow so a mistaken proposed edit cannot be
        # silently applied to the uploaded session document.
        queued = self._json("POST", "/v1/chat/async", json={**common, "approval_mode": "ask_every_time"})
        job_id = queued["job_id"]
        deadline = time.monotonic() + self.settings.poll_timeout_seconds
        polls: list[dict[str, Any]] = []
        while True:
            job = self.get_job(job_id)
            polls.append(job)
            status = job.get("status")
            if status in {"awaiting_approval", "completed", "failed", "cancelled"}:
                break
            if time.monotonic() >= deadline:
                raise SuperDocsError(f"Async job {job_id} did not finish within {self.settings.poll_timeout_seconds:g}s; it may still be processing.")
            time.sleep(self.settings.poll_interval_seconds)
        result = job.get("result") or {}
        metadata = job.get("metadata") or {}
        pending_changes=resolve_pending_changes(metadata.get("pending_changes") or [],chunk_heading_paths)
        evidence = {
            "pending_changes": pending_changes,
            "chunk_heading_paths": chunk_heading_paths,
            "intermediate_responses": metadata.get("intermediate_responses") or [],
            "document_changes": result.get("document_changes"),
            "usage": result.get("usage"),
            "progress": job.get("progress"),
            "change_ids": [item.get("change_id") for item in pending_changes if item.get("change_id")],
            "chunk_ids": [item.get("chunk_id") for item in pending_changes if item.get("chunk_id")],
        }
        error = job.get("error") if status in {"failed", "cancelled"} else None
        return RunResult(status, session_id, result.get("response"), evidence, {"upload": upload, "queued": queued, "job": job}, (time.perf_counter() - started) * 1000, _ops(result), job_id, error)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/jobs/{job_id}")


    def poll_after_approval(self, job_id: str, approved_change_ids: list[str] | None = None) -> dict[str, Any]:
        deadline = time.monotonic() + self.settings.poll_timeout_seconds
        approved=set(approved_change_ids or [])
        while True:
            job = self.get_job(job_id)
            status=job.get("status")
            current_ids={str(item.get("change_id")) for item in ((job.get("metadata") or {}).get("pending_changes") or []) if item.get("change_id")}
            if status=="awaiting_approval" and approved and current_ids==approved:
                pass
            elif status in {"awaiting_approval", "completed", "failed", "cancelled"}:
                return job
            if time.monotonic() >= deadline:
                raise SuperDocsError(f"Async job {job_id} did not finish within {self.settings.poll_timeout_seconds:g}s after approval; it may still be processing.")
            time.sleep(self.settings.poll_interval_seconds)

    def list_session_documents(self, session_id: str) -> dict[str, Any]:
        return self._json("GET", f"/v1/sessions/{session_id}/documents", params={"include_html": "true"})

    def decide_changes(self, session_id: str, job_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        decisions = [{"change_id": item["change_id"], "approved": bool(item["approved"]), "feedback": item.get("feedback")} for item in changes]
        return self._json("POST", f"/v1/chat/{session_id}/approve", json={"job_id": job_id, "approved": all(x["approved"] for x in decisions), "changes": decisions})

    def export(self, session_id: str, format: str = "docx") -> tuple[bytes, str]:
        response = self.http.post("/v1/documents/export", json={"session_id": session_id, "format": format})
        if response.is_error:
            raise SuperDocsError(f"SuperDocs export HTTP {response.status_code}: {response.text[:1000]}")
        return response.content, response.headers.get("content-type", "application/octet-stream")


def _ops(payload: dict[str, Any]) -> int:
    usage = payload.get("usage") or {}
    return int(usage.get("ops_charged") or (1 if usage.get("was_billable") else 0))


class FakeSuperDocsClient:
    """Deterministic local client used by tests and optional demo mode."""
    def __init__(self, async_states: list[str] | None = None, fail: bool = False, post_approval_html: str | None = None, approval_jobs: list[dict[str, Any]] | None = None, recovery_job: dict[str, Any] | None = None):
        self.async_states = async_states or ["in_progress", "awaiting_approval"]
        self.fail = fail
        self.jobs: dict[str, int] = {}
        self.approval_calls: list[dict[str, Any]] = []
        self.post_approval_html = post_approval_html or '<h1 data-chunk-id="h1">Projects</h1><p data-chunk-id="observed-chunk-1">Deadline: March 27.</p>'
        self.approval_jobs = approval_jobs or [{"status":"completed","result":{"response":"Applied","document_changes":{"chunk_diffs":[]}},"metadata":{}}]
        self.approval_poll_index = 0
        self.followup_calls: list[dict[str, Any]] = []
        self.recovery_job = recovery_job or {"status":"awaiting_approval","result":{"response":"I proposed the guided correction.","usage":{"ops_charged":1}},"metadata":{"awaiting_kind":"change_review","pending_changes":[{"change_id":"recovery-change-1","operation":"edit","chunk_id":"observed-chunk-1","old_html":"<p>Before</p>","new_html":"<p>After</p>"}]}}
        self.last_decision_approved: bool | None = None

    def run(self, case: dict[str, Any], document: dict[str, Any]) -> RunResult:
        if self.fail:
            raise SuperDocsError("Fake upstream error")
        session = f"fake_session_{case['id']}"
        if case["case_type"] == "search":
            raw = {"response": case.get("expected_answer") or "Please clarify which repeated section you mean.", "session_id": session, "usage": {"ops_charged": 1}}
            return RunResult("completed", session, raw["response"], {"usage": raw["usage"]}, {"upload": {"chunks_count": 4}, "chat": raw}, 12.5, 1)
        job_id = f"fake_job_{case['id']}"
        pre_html = '<h1 data-chunk-id="h1">Projects</h1><p data-chunk-id="observed-chunk-1">Deadline: March 20.</p>'
        pending = [{"change_id": "change-1", "operation": "edit", "chunk_id": "observed-chunk-1", "document_id":"doc_primary", "old_html": "<p data-chunk-id=\"observed-chunk-1\">Deadline: March 20.</p>", "new_html": "<p data-chunk-id=\"observed-chunk-1\">Deadline: March 27.</p>", "ai_explanation": "Updates the named deadline."}]
        self.jobs[job_id] = 0
        return RunResult("awaiting_approval", session, "I proposed the requested deadline update.", {"pending_changes": pending, "chunk_heading_paths":{"h1":"Projects","observed-chunk-1":"Projects"}, "usage": {"ops_charged": 1}}, {"upload": {"chunks_count": 2,"html":pre_html,"session_id":session}, "queued": {"job_id": job_id}, "job": {"status": "awaiting_approval", "metadata": {"pending_changes": pending,"awaiting_kind":"change_review"}}}, 24.0, 1, job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        index = self.jobs.get(job_id, 0)
        status = self.async_states[min(index, len(self.async_states) - 1)]
        self.jobs[job_id] = index + 1
        return {"job_id": job_id, "status": status, "progress": 100 if status != "in_progress" else 50}

    def decide_changes(self, session_id: str, job_id: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        payload={"job_id":job_id,"approved":all(bool(item.get("approved")) for item in changes),"changes":changes}
        self.last_decision_approved=payload["approved"]
        self.approval_calls.append({"session_id":session_id,**payload})
        return {"job_id": job_id, "status": "processing", "decisions": changes, "approved":payload["approved"]}

    def poll_after_approval(self, job_id: str, approved_change_ids: list[str] | None = None) -> dict[str, Any]:
        job=self.recovery_job if self.last_decision_approved is False else self.approval_jobs[min(self.approval_poll_index,len(self.approval_jobs)-1)]
        self.approval_poll_index+=1
        return {"job_id":job_id,"session_id":"fake", "job_type":"chat", "progress":100, **job}

    def list_session_documents(self, session_id: str) -> dict[str, Any]:
        return {"documents":[{"document_id":"doc_primary","focused":True,"html":self.post_approval_html}]}

    def export(self, session_id: str, format: str = "docx") -> tuple[bytes, str]:
        return b"fake export", "application/octet-stream"
