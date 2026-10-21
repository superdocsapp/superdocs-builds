"""Slack-to-SuperDocs handoff service.

The HTTP process verifies and acknowledges Slack requests quickly. A separate
worker owns provider calls so a Slack retry or a process restart cannot create
duplicate SuperDocs sessions. The database stores IDs and Slack file references
only; document bytes, generated proposals, and credentials are never persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel


SUPERDOCS_BASE_URL = os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app").rstrip("/")
DATABASE_PATH = Path(os.getenv("SLACK_INTAKE_DATABASE", "./data/slack-intake.sqlite3"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_BYTES", str(25 * 1024 * 1024)))


@dataclass(frozen=True)
class Settings:
    superdocs_api_key: str
    slack_bot_token: str
    slack_signing_secret: str

    @classmethod
    def from_env(cls, *, require_integrations: bool = True) -> "Settings":
        values = {
            "SUPERDOCS_API_KEY": os.getenv("SUPERDOCS_API_KEY", ""),
            "SLACK_BOT_TOKEN": os.getenv("SLACK_BOT_TOKEN", ""),
            "SLACK_SIGNING_SECRET": os.getenv("SLACK_SIGNING_SECRET", ""),
        }
        required = ("SLACK_SIGNING_SECRET",) if not require_integrations else tuple(values)
        missing = [name for name in required if not values[name]]
        if missing:
            raise RuntimeError("Missing required server configuration: " + ", ".join(missing))
        return cls(values["SUPERDOCS_API_KEY"], values["SLACK_BOT_TOKEN"], values["SLACK_SIGNING_SECRET"])


def now() -> str:
    return datetime.now(UTC).isoformat()


def plain_text(markup: str) -> str:
    value = markup.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    value = value.replace("</p>", "\n")
    while "<" in value and ">" in value:
        start, end = value.find("<"), value.find(">", value.find("<"))
        if end < 0:
            break
        value = value[:start] + value[end + 1 :]
    return html.unescape(value).strip()


def slack_mrkdwn(value: str) -> str:
    """Render provider/file text as Slack text, never as Slack formatting."""
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def code_excerpt(value: str, *, limit: int = 900) -> str:
    cleaned = slack_mrkdwn(value).replace("`", "'").strip()
    return cleaned[:limit] + ("…" if len(cleaned) > limit else "")


def proposals_from(value: Any) -> list[dict[str, Any]]:
    parsed = value
    for _ in range(3):
        if not isinstance(parsed, str):
            break
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            break
    if isinstance(parsed, dict):
        for key in ("pending_changes", "proposed_change_batch", "proposed_changes", "changes"):
            if key in parsed:
                return proposals_from(parsed[key])
        return proposals_from(parsed.get("content", []))
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def signed_slack_request(secret: str, timestamp: str | None, signature: str | None, raw_body: bytes) -> bool:
    if not timestamp or not signature:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    expected = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def slack_file_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in {"files.slack.com", "files.slack.com."}


def safe_failure_code(error: Exception) -> str:
    """Retain a supportable error class without persisting remote payloads."""
    message = str(error)
    slack = __import__("re").fullmatch(r"Slack API ([A-Za-z.]+) failed: ([a-z_]+)", message)
    if slack:
        return "slack_" + slack.group(1).replace(".", "_") + "_" + slack.group(2)
    provider = __import__("re").fullmatch(r"SuperDocs(?: export)? returned HTTP ([0-9]{3})\.", message)
    if provider:
        return "superdocs_http_" + provider.group(1)
    known = {
        "Slack file is unavailable or exceeds the configured intake size limit.": "slack_file_unavailable_or_too_large",
        "Slack returned an unsupported private-file URL.": "slack_file_url_rejected",
        "The Slack file exceeds the configured intake size limit.": "slack_file_too_large",
        "SuperDocs did not return a usable upload target.": "superdocs_upload_target_invalid",
        "SuperDocs did not return one isolated document.": "superdocs_document_roster_invalid",
        "SuperDocs did not return editable document content.": "superdocs_document_content_invalid",
        "SuperDocs did not return a review job.": "superdocs_job_missing",
    }
    return known.get(message, "handoff_runtime_failure")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS handoffs (
              id TEXT PRIMARY KEY, created_at TEXT NOT NULL, team_id TEXT NOT NULL,
              channel_id TEXT NOT NULL, thread_ts TEXT NOT NULL, requester_id TEXT NOT NULL,
              file_id TEXT NOT NULL, file_name TEXT NOT NULL, file_mimetype TEXT NOT NULL,
              instruction TEXT NOT NULL, status TEXT NOT NULL, action TEXT NOT NULL,
              decision INTEGER, session_id TEXT, document_id TEXT, job_id TEXT,
              status_message_ts TEXT, last_error TEXT
            )"""
        )
        self.connection.commit()

    def create(self, record: dict[str, Any]) -> sqlite3.Row:
        self.connection.execute(
            """INSERT INTO handoffs
            (id, created_at, team_id, channel_id, thread_ts, requester_id, file_id, file_name,
             file_mimetype, instruction, status, action, decision)
            VALUES (:id, :created_at, :team_id, :channel_id, :thread_ts, :requester_id, :file_id,
             :file_name, :file_mimetype, :instruction, 'queued', 'intake', NULL)""",
            record,
        )
        self.connection.commit()
        return self.get(record["id"])

    def get(self, handoff_id: str) -> sqlite3.Row:
        row = self.connection.execute("SELECT * FROM handoffs WHERE id = ?", (handoff_id,)).fetchone()
        if row is None:
            raise KeyError(handoff_id)
        return row

    def enqueue(self, handoff_id: str, action: str, decision: bool | None = None) -> sqlite3.Row:
        allowed = {"refresh", "decision", "export"}
        if action not in allowed:
            raise ValueError("Unsupported handoff action.")
        self.connection.execute(
            "UPDATE handoffs SET status = 'queued', action = ?, decision = ?, last_error = NULL WHERE id = ?",
            (action, int(decision) if decision is not None else None, handoff_id),
        )
        self.connection.commit()
        return self.get(handoff_id)

    def retry_latest_export(self, channel_id: str, requester_id: str) -> sqlite3.Row | None:
        row = self.connection.execute(
            """SELECT id FROM handoffs
            WHERE channel_id = ? AND requester_id = ? AND status = 'failed' AND session_id IS NOT NULL
            ORDER BY created_at DESC LIMIT 1""",
            (channel_id, requester_id),
        ).fetchone()
        return self.enqueue(row["id"], "export") if row else None

    def claim_next(self) -> sqlite3.Row | None:
        row = self.connection.execute("SELECT id FROM handoffs WHERE status = 'queued' ORDER BY created_at LIMIT 1").fetchone()
        if row is None:
            return None
        updated = self.connection.execute("UPDATE handoffs SET status = 'processing' WHERE id = ? AND status = 'queued'", (row["id"],))
        self.connection.commit()
        return self.get(row["id"]) if updated.rowcount == 1 else None

    def complete_intake(self, handoff_id: str, session_id: str, document_id: str, job_id: str) -> sqlite3.Row:
        self.connection.execute(
            "UPDATE handoffs SET status = 'review_pending', session_id = ?, document_id = ?, job_id = ?, action = 'none', last_error = NULL WHERE id = ?",
            (session_id, document_id, job_id, handoff_id),
        )
        self.connection.commit()
        return self.get(handoff_id)

    def set_status(self, handoff_id: str, status: str, *, error: str | None = None) -> sqlite3.Row:
        self.connection.execute("UPDATE handoffs SET status = ?, action = 'none', last_error = ? WHERE id = ?", (status, error, handoff_id))
        self.connection.commit()
        return self.get(handoff_id)

    def set_message_ts(self, handoff_id: str, message_ts: str) -> sqlite3.Row:
        self.connection.execute("UPDATE handoffs SET status_message_ts = ? WHERE id = ?", (message_ts, handoff_id))
        self.connection.commit()
        return self.get(handoff_id)

    def close(self) -> None:
        self.connection.close()


class SlackApi:
    def __init__(self, token: str, *, client: httpx.AsyncClient | None = None):
        self.client = client or httpx.AsyncClient(base_url="https://slack.com/api/", headers={"Authorization": f"Bearer {token}"}, timeout=httpx.Timeout(20.0, connect=10.0))

    async def call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.post(method, json=payload)
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or not value.get("ok"):
            raise RuntimeError("Slack API " + method + " failed: " + str(value.get("error", "unknown_error")))
        return value

    async def file(self, file_id: str) -> dict[str, Any]:
        # files.info is documented as a GET endpoint. Sending it through the
        # JSON POST helper causes Slack to reject otherwise valid file IDs as
        # invalid arguments.
        response = await self.client.get("files.info", params={"file": file_id})
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or not value.get("ok"):
            raise RuntimeError("Slack API files.info failed: " + str(value.get("error", "unknown_error")))
        return value.get("file", {})

    async def reserve_upload(self, filename: str, length: int) -> tuple[str, str]:
        response = await self.client.get("files.getUploadURLExternal", params={"filename": filename, "length": str(length)})
        response.raise_for_status()
        value = response.json()
        if not isinstance(value, dict) or not value.get("ok"):
            raise RuntimeError("Slack API files.getUploadURLExternal failed: " + str(value.get("error", "unknown_error")))
        upload_url, file_id = value.get("upload_url"), value.get("file_id")
        if not isinstance(upload_url, str) or not isinstance(file_id, str):
            raise RuntimeError("Slack API files.getUploadURLExternal failed: malformed_response")
        return upload_url, file_id

    async def download(self, url: str) -> bytes:
        if not slack_file_url(url):
            raise RuntimeError("Slack returned an unsupported private-file URL.")
        response = await self.client.get(url)
        response.raise_for_status()
        if len(response.content) > MAX_DOCUMENT_BYTES:
            raise RuntimeError("The Slack file exceeds the configured intake size limit.")
        return response.content

    async def status_message(self, handoff: sqlite3.Row, blocks: list[dict[str, Any]]) -> sqlite3.Row:
        payload = {"channel": handoff["channel_id"], "text": "SuperDocs Handoff update", "blocks": blocks}
        if handoff["status_message_ts"]:
            payload["ts"] = handoff["status_message_ts"]
            await self.call("chat.update", payload)
            return handoff
        payload["thread_ts"] = handoff["thread_ts"]
        response = await self.call("chat.postMessage", payload)
        return store().set_message_ts(handoff["id"], response["ts"])

    async def open_modal(self, trigger_id: str, view: dict[str, Any]) -> None:
        await self.call("views.open", {"trigger_id": trigger_id, "view": view})

    async def upload_pdf(self, handoff: sqlite3.Row, content: bytes) -> None:
        upload_url, file_id = await self.reserve_upload("superdocs-reviewed.pdf", len(content))
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            uploaded = await client.post(upload_url, content=content, headers={"Content-Type": "application/pdf"})
            uploaded.raise_for_status()
        await self.call("files.completeUploadExternal", {"files": [{"id": file_id, "title": "SuperDocs reviewed PDF"}], "channel_id": handoff["channel_id"], "thread_ts": handoff["thread_ts"]})

    async def close(self) -> None:
        await self.client.aclose()


class SuperDocsApi:
    def __init__(self, api_key: str, *, client: httpx.AsyncClient | None = None, upload_transport: httpx.AsyncBaseTransport | None = None):
        self.client = client or httpx.AsyncClient(base_url=SUPERDOCS_BASE_URL, headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True)
        self.upload_transport = upload_transport

    async def json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = await self.client.request(method, path, json=payload)
        if response.is_error:
            raise RuntimeError(f"SuperDocs returned HTTP {response.status_code}.")
        value = response.json()
        if not isinstance(value, dict):
            raise RuntimeError("SuperDocs returned an unexpected response.")
        return value

    async def intake(self, filename: str, content_type: str, document: bytes, instruction: str) -> tuple[str, str, str]:
        session_id = str(uuid.uuid4())
        await self.json("POST", "/v1/sessions/init", {"session_id": session_id})
        upload = await self.json("POST", "/v1/uploads", {"filename": filename, "content_type": content_type, "size_bytes": len(document), "purpose": "document"})
        upload_id, upload_url = upload.get("upload_id"), upload.get("upload_url")
        if not isinstance(upload_id, str) or not isinstance(upload_url, str):
            raise RuntimeError("SuperDocs did not return a usable upload target.")
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True, transport=self.upload_transport) as client:
            response = await client.put(upload_url, content=document, headers={"Content-Type": content_type})
            response.raise_for_status()
        await self.json("POST", f"/v1/uploads/{upload_id}/process", {"session_id": session_id, "filename": filename, "parse_mode": "document", "return_html": True})
        roster = await self.json("GET", f"/v1/sessions/{session_id}/documents?include_html=true")
        documents = roster.get("documents")
        if not isinstance(documents, list) or len(documents) != 1 or not isinstance(documents[0], dict):
            raise RuntimeError("SuperDocs did not return one isolated document.")
        document_id, document_html = documents[0].get("document_id"), documents[0].get("html")
        if not isinstance(document_id, str) or not isinstance(document_html, str) or not document_html:
            raise RuntimeError("SuperDocs did not return editable document content.")
        job = await self.json("POST", "/v1/chat/async", {"message": instruction, "document_html": document_html, "session_id": session_id, "document_id": document_id, "async_mode": True, "approval_mode": "ask_every_time", "response_mode": "compact"})
        job_id = job.get("job_id")
        if not isinstance(job_id, str):
            raise RuntimeError("SuperDocs did not return a review job.")
        return session_id, document_id, job_id

    async def job(self, job_id: str) -> dict[str, Any]:
        return await self.json("GET", f"/v1/jobs/{job_id}")

    async def approve(self, session_id: str, job_id: str, change_id: str, approved: bool) -> None:
        await self.json("POST", f"/v1/chat/{session_id}/approve", {"job_id": job_id, "approved": approved, "changes": [{"change_id": change_id, "approved": approved}]})

    async def export(self, session_id: str) -> bytes:
        response = await self.client.post("/v1/documents/export", json={"session_id": session_id, "format": "pdf", "options": {"filename": "superdocs-reviewed.pdf"}})
        if response.is_error:
            raise RuntimeError(f"SuperDocs export returned HTTP {response.status_code}.")
        return response.content

    async def close(self) -> None:
        await self.client.aclose()


def blocks(handoff: sqlite3.Row, proposal: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    stages = {
        "queued": ("01 / INTAKE", "Your file is queued at the document desk."),
        "processing": ("02 / PROCESSING", "SuperDocs is preparing the document."),
        "review_pending": ("02 / PROCESSING", "SuperDocs is working. Check back for a proposed revision."),
        "awaiting_approval": ("03 / REVIEW DESK", "One proposed revision is waiting for your sign-off."),
        "approval_submitted": ("04 / APPLYING", "Your decision is with SuperDocs. The document is being finalized."),
        "completed": ("05 / EXPORT COUNTER", "Your reviewed PDF is ready to collect."),
        "exported": ("FILED", "The reviewed PDF has been delivered to this thread."),
        "failed": ("ATTENTION", "This handoff needs a quick check."),
    }
    stage, guidance = stages.get(handoff["status"], ("IN PROGRESS", "This handoff is still active."))
    file_name = slack_mrkdwn(handoff["file_name"])
    result: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": "SuperDocs · Document Desk", "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*▣ {file_name}*\n{guidance}"}, "fields": [
            {"type": "mrkdwn", "text": f"*STAGE*\n`{stage}`"},
            {"type": "mrkdwn", "text": "*MODE*\nHuman review on"},
        ]},
        {"type": "divider"},
    ]
    if proposal:
        old_text = code_excerpt(plain_text(str(proposal.get("old_html", ""))))
        new_text = code_excerpt(plain_text(str(proposal.get("new_html", ""))))
        result.append({"type": "section", "text": {"type": "mrkdwn", "text": "*03 / PROPOSED REVISION*\nCompare the document’s before and after. Nothing changes without your decision."}})
        result.append({"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*BEFORE*\n```{old_text}```"},
            {"type": "mrkdwn", "text": f"*AFTER*\n```{new_text}```"},
        ]})
        result.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Approve revision"}, "style": "primary", "action_id": "superdocs_approve", "value": handoff["id"]},
            {"type": "button", "text": {"type": "plain_text", "text": "Keep original"}, "action_id": "superdocs_reject", "value": handoff["id"]},
        ]})
    elif handoff["status"] in {"review_pending", "approval_submitted"}:
        result.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Refresh document desk"}, "action_id": "superdocs_refresh", "value": handoff["id"]}]})
    elif handoff["status"] == "completed":
        result.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Collect reviewed PDF"}, "style": "primary", "action_id": "superdocs_export", "value": handoff["id"]}]})
    elif handoff["status"] == "failed":
        exported_document_exists = bool(handoff["session_id"])
        detail = "SuperDocs completed, but returning its PDF to Slack failed. Use `/superdocs retry-export` or the button below." if exported_document_exists else "The document was not changed. Retry from the original Slack file."
        if handoff["last_error"]:
            detail += " Failure code: `" + handoff["last_error"] + "`."
        result.append({"type": "context", "elements": [{"type": "mrkdwn", "text": detail}]})
        if exported_document_exists:
            result.append({"type": "actions", "elements": [{"type": "button", "text": {"type": "plain_text", "text": "Retry PDF export"}, "action_id": "superdocs_export", "value": handoff["id"]}]})
    return result


_store: Store | None = None


def store() -> Store:
    if _store is None:
        raise RuntimeError("Store is not initialized.")
    return _store


app = FastAPI(title="SuperDocs Slack Handoff", version="1.0.0")


@app.on_event("startup")
async def startup() -> None:
    global _store
    # Slack provides this secret as soon as the shell app is created. Keeping
    # the callback server runnable with that one secret lets Slack verify the
    # interaction URL before the app has been installed and issued a bot token.
    Settings.from_env(require_integrations=False)
    _store = Store(DATABASE_PATH)


@app.on_event("shutdown")
async def shutdown() -> None:
    if _store:
        _store.close()


async def verified_body(request: Request) -> bytes:
    raw = await request.body()
    settings = Settings.from_env()
    if not signed_slack_request(settings.slack_signing_secret, request.headers.get("x-slack-request-timestamp"), request.headers.get("x-slack-signature"), raw):
        raise HTTPException(status_code=401, detail="Invalid Slack request signature.")
    return raw


@app.get("/health")
async def health() -> dict[str, str]:
    Settings.from_env(require_integrations=False)
    return {"status": "ok"}


@app.post("/slack/commands")
async def command(request: Request) -> dict[str, str]:
    raw = await verified_body(request)
    form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    if form.get("text", [""])[0].strip() == "retry-export":
        handoff = store().retry_latest_export(form.get("channel_id", [""])[0], form.get("user_id", [""])[0])
        if handoff:
            return {"response_type": "ephemeral", "text": "Queued the completed SuperDocs PDF for delivery to this thread."}
        return {"response_type": "ephemeral", "text": "No failed completed SuperDocs export was found for you in this channel."}
    return {"response_type": "ephemeral", "text": "Use *Send file to SuperDocs* from the message actions menu on a Slack message containing one document."}


def modal(payload: dict[str, Any], file: dict[str, Any]) -> dict[str, Any]:
    metadata = {"team_id": payload["team"]["id"], "channel_id": payload["channel"]["id"], "thread_ts": payload["message"].get("thread_ts", payload["message"]["ts"]), "requester_id": payload["user"]["id"], "file_id": file["id"], "file_name": file.get("name", "document"), "file_mimetype": file.get("mimetype", "application/octet-stream")}
    return {"type": "modal", "callback_id": "superdocs_intake_submit", "private_metadata": json.dumps(metadata), "title": {"type": "plain_text", "text": "SuperDocs Desk"}, "submit": {"type": "plain_text", "text": "Start handoff"}, "close": {"type": "plain_text", "text": "Cancel"}, "blocks": [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*▣ DOCUMENT INTAKE*\n`{slack_mrkdwn(metadata['file_name'])}` is headed to SuperDocs. You will review every proposed revision before it is finalized."}},
        {"type": "divider"},
        {"type": "input", "block_id": "instruction", "label": {"type": "plain_text", "text": "Your instruction"}, "hint": {"type": "plain_text", "text": "Keep this concrete: what should SuperDocs improve, check, or change?"}, "element": {"type": "plain_text_input", "action_id": "value", "multiline": True, "min_length": 1, "max_length": 3000, "initial_value": "Review this document for clarity and completeness. Propose only necessary edits."}},
    ]}


@app.post("/slack/interactions")
async def interactions(request: Request) -> dict[str, Any]:
    raw = await verified_body(request)
    form = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    payload = json.loads(form.get("payload", ["{}"])[0])
    settings = Settings.from_env()
    slack = SlackApi(settings.slack_bot_token)
    try:
        if payload.get("type") == "message_action" and payload.get("callback_id") == "superdocs_intake_file":
            files = payload.get("message", {}).get("files", [])
            if len(files) != 1 or not isinstance(files[0], dict):
                return {"response_action": "errors", "errors": {"": "Choose a message containing exactly one Slack file."}}
            await slack.open_modal(payload["trigger_id"], modal(payload, files[0]))
        elif payload.get("type") == "view_submission" and payload.get("view", {}).get("callback_id") == "superdocs_intake_submit":
            metadata = json.loads(payload["view"]["private_metadata"])
            instruction = payload["view"]["state"]["values"]["instruction"]["value"]["value"].strip()
            record = dict(metadata, id=str(uuid.uuid4()), created_at=now(), instruction=instruction)
            store().create(record)
        elif payload.get("type") == "block_actions":
            action = payload.get("actions", [{}])[0]
            handoff_id = action.get("value")
            action_name = {"superdocs_refresh": "refresh", "superdocs_approve": "decision", "superdocs_reject": "decision", "superdocs_export": "export"}.get(action.get("action_id"))
            if not isinstance(handoff_id, str) or not action_name:
                raise HTTPException(status_code=400, detail="Unsupported Slack action.")
            handoff = store().get(handoff_id)
            if payload.get("user", {}).get("id") != handoff["requester_id"]:
                raise HTTPException(status_code=403, detail="Only the person who started this handoff can decide it.")
            store().enqueue(handoff_id, action_name, action.get("action_id") == "superdocs_approve" if action_name == "decision" else None)
        return {}
    finally:
        await slack.close()


class WorkerResult(BaseModel):
    processed: int


async def process_one() -> bool:
    handoff = store().claim_next()
    if handoff is None:
        return False
    settings = Settings.from_env()
    slack, superdocs = SlackApi(settings.slack_bot_token), SuperDocsApi(settings.superdocs_api_key)
    try:
        if handoff["action"] == "intake":
            file = await slack.file(handoff["file_id"])
            url = file.get("url_private_download")
            if not isinstance(url, str) or file.get("size", 0) > MAX_DOCUMENT_BYTES:
                raise RuntimeError("Slack file is unavailable or exceeds the configured intake size limit.")
            document = await slack.download(url)
            session_id, document_id, job_id = await superdocs.intake(handoff["file_name"], handoff["file_mimetype"], document, handoff["instruction"])
            handoff = store().complete_intake(handoff["id"], session_id, document_id, job_id)
            await slack.status_message(handoff, blocks(handoff))
        elif handoff["action"] == "refresh":
            job = await superdocs.job(handoff["job_id"])
            status = str(job.get("status", "review_pending"))
            metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
            proposals = proposals_from(metadata.get("pending_changes", metadata.get("proposed_change_batch", [])))
            handoff = store().set_status(handoff["id"], "awaiting_approval" if proposals else status)
            await slack.status_message(handoff, blocks(handoff, proposals[0] if len(proposals) == 1 else None))
        elif handoff["action"] == "decision":
            job = await superdocs.job(handoff["job_id"])
            metadata = job.get("metadata") if isinstance(job.get("metadata"), dict) else {}
            proposals = proposals_from(metadata.get("pending_changes", metadata.get("proposed_change_batch", [])))
            if len(proposals) != 1 or not isinstance(proposals[0].get("change_id"), str):
                raise RuntimeError("SuperDocs no longer has one actionable proposal for this handoff.")
            proposal = proposals[0]
            replacement = plain_text(str(proposal.get("new_html", "")))
            if not replacement or str(proposal.get("operation", "")).lower() in {"create_document", "delete_document"}:
                raise RuntimeError("SuperDocs returned an unsupported structural or empty proposal.")
            await superdocs.approve(handoff["session_id"], handoff["job_id"], proposal["change_id"], bool(handoff["decision"]))
            handoff = store().set_status(handoff["id"], "approval_submitted")
            await slack.status_message(handoff, blocks(handoff))
        elif handoff["action"] == "export":
            document = await superdocs.export(handoff["session_id"])
            await slack.upload_pdf(handoff, document)
            handoff = store().set_status(handoff["id"], "exported")
            await slack.status_message(handoff, blocks(handoff))
        return True
    except Exception as error:
        handoff = store().set_status(handoff["id"], "failed", error=safe_failure_code(error))
        await slack.status_message(handoff, blocks(handoff))
        return True
    finally:
        await slack.close()
        await superdocs.close()
