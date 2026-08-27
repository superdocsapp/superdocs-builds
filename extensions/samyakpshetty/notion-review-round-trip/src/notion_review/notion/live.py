"""Live Notion client over HTTP, plus the JSON ↔ model mapping.

A thin mapping onto Notion's REST API: retrieve a page, page through a block's children, update
one block's rich text in place, and attach a comment. A client-side rate limiter keeps us under
Notion's ~3 requests/second, and 429/5xx are retried with backoff. The mapping helpers are pure
functions, tested directly against sample Notion JSON with no network.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from notion_review.config import Config
from notion_review.logging import get_logger
from notion_review.notion.base import NotionError, NotionNotFoundError
from notion_review.notion.models import (
    Annotations,
    Block,
    ChildrenPage,
    Comment,
    DatabaseRef,
    Page,
    QueueRow,
    RichText,
    plain_text,
    split_rich_text,
)

_log = get_logger("notion_review.notion.live")
_RETRYABLE = frozenset({429, 500, 502, 503, 504})
_API = "https://api.notion.com"


class LiveNotionClient:
    """HTTP implementation of :class:`~notion_review.notion.base.NotionClient`."""

    def __init__(
        self, *, token: str, version: str = "2022-06-28", config: Config | None = None
    ) -> None:
        self._client = httpx.Client(
            base_url=_API,
            # No default Content-Type: httpx sets ``application/json`` for a ``json=`` body and
            # the correct multipart boundary for a file upload. A fixed header would break the
            # second, and Notion rejects a multipart body labelled as JSON.
            headers={"Authorization": f"Bearer {token}", "Notion-Version": version},
            timeout=httpx.Timeout(30.0),
        )
        self._min_interval = config.notion_min_interval_s if config else 0.34
        self._max_retries = config.notion_max_retries if config else 5
        self._last_call = 0.0

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            resp = self._client.request(method, path, json=json, params=params, files=files)
            self._last_call = time.monotonic()
            if resp.status_code == 404:
                raise NotionNotFoundError(f"{method} {path} -> 404")
            if resp.status_code in _RETRYABLE and attempt < self._max_retries:
                delay = float(resp.headers.get("Retry-After", 0)) or 0.5 * (2**attempt)
                time.sleep(delay)
                attempt += 1
                continue
            if resp.status_code >= 400:
                raise NotionError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}")
            return resp

    def retrieve_page(self, page_id: str) -> Page:
        data = self._request("GET", f"/v1/pages/{page_id}").json()
        return Page(id=data["id"], title=page_title(data), url=data.get("url", ""))

    def retrieve_block(self, block_id: str) -> Block:
        return block_from_json(self._request("GET", f"/v1/blocks/{block_id}").json())

    def list_block_children(
        self, block_id: str, *, start_cursor: str | None = None, page_size: int = 100
    ) -> ChildrenPage:
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        data = self._request("GET", f"/v1/blocks/{block_id}/children", params=params).json()
        return ChildrenPage(
            results=[block_from_json(b) for b in data.get("results", [])],
            next_cursor=data.get("next_cursor"),
            has_more=data.get("has_more", False),
        )

    def update_block(self, block_id: str, *, block_type: str, rich_text: list[RichText]) -> Block:
        # Split any over-long run: Notion rejects a rich-text object past 2000 characters.
        runs = split_rich_text(rich_text)
        payload = {block_type: {"rich_text": [rich_to_json(rt) for rt in runs]}}
        return block_from_json(
            self._request("PATCH", f"/v1/blocks/{block_id}", json=payload).json()
        )

    def update_table_row(self, block_id: str, *, cells: list[str]) -> Block:
        payload = {
            "table_row": {
                "cells": [[rich_to_json(rt) for rt in plain_text(text)] for text in cells]
            }
        }
        return block_from_json(
            self._request("PATCH", f"/v1/blocks/{block_id}", json=payload).json()
        )

    def create_comment(
        self,
        *,
        rich_text: list[RichText],
        page_id: str | None = None,
        block_id: str | None = None,
    ) -> Comment:
        payload = {
            "parent": {"block_id": block_id} if block_id else {"page_id": page_id},
            "rich_text": [rich_to_json(rt) for rt in rich_text],
        }
        try:
            data = self._request("POST", "/v1/comments", json=payload).json()
        except NotionError:
            # Block-level comments need a recent API version; fall back to a page comment.
            if block_id and page_id:
                payload["parent"] = {"page_id": page_id}
                data = self._request("POST", "/v1/comments", json=payload).json()
            else:
                raise
        return _comment_from_json(data, fallback_parent=block_id or page_id or "")

    def list_comments(self, block_id: str) -> list[Comment]:
        comments: list[Comment] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"block_id": block_id, "page_size": 100}
            if cursor:
                params["start_cursor"] = cursor
            data = self._request("GET", "/v1/comments", params=params).json()
            comments.extend(
                _comment_from_json(item, fallback_parent=block_id)
                for item in data.get("results", [])
            )
            if not data.get("has_more"):
                return comments
            cursor = data.get("next_cursor")

    # -- the in-Notion review queue -------------------------------------------
    def create_database(
        self, *, parent_page_id: str, title: str, properties: dict[str, Any]
    ) -> DatabaseRef:
        payload = {
            "parent": {"type": "page_id", "page_id": parent_page_id},
            "title": [{"type": "text", "text": {"content": title}}],
            "properties": properties,
        }
        data = self._request("POST", "/v1/databases", json=payload).json()
        return DatabaseRef(id=str(data["id"]), url=data.get("url", ""))

    def search_databases(self, query: str) -> list[DatabaseRef]:
        found: list[DatabaseRef] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {
                "query": query,
                "filter": {"property": "object", "value": "database"},
                "page_size": 100,
            }
            if cursor:
                body["start_cursor"] = cursor
            data = self._request("POST", "/v1/search", json=body).json()
            found.extend(
                DatabaseRef(
                    id=str(item["id"]),
                    url=item.get("url", ""),
                    title="".join(part.get("plain_text", "") for part in (item.get("title") or [])),
                    archived=bool(item.get("archived") or item.get("in_trash")),
                )
                for item in data.get("results", [])
            )
            if not data.get("has_more"):
                return found
            cursor = data.get("next_cursor")

    def create_row(self, *, database_id: str, properties: dict[str, Any]) -> QueueRow:
        payload = {"parent": {"database_id": database_id}, "properties": properties}
        data = self._request("POST", "/v1/pages", json=payload).json()
        return QueueRow(
            page_id=data["id"],
            status=_row_status(data),
            url=data.get("url", ""),
            properties=data.get("properties") or {},
        )

    def query_database(self, database_id: str) -> list[QueueRow]:
        rows: list[QueueRow] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = self._request("POST", f"/v1/databases/{database_id}/query", json=body).json()
            rows.extend(
                QueueRow(
                    page_id=r["id"],
                    status=_row_status(r),
                    url=r.get("url", ""),
                    properties=r.get("properties") or {},
                )
                for r in data.get("results", [])
            )
            if not data.get("has_more"):
                return rows
            cursor = data.get("next_cursor")

    def update_row(self, *, page_id: str, properties: dict[str, Any]) -> None:
        self._request("PATCH", f"/v1/pages/{page_id}", json={"properties": properties})

    def upload_file(self, *, content: bytes, filename: str, content_type: str) -> str:
        """Create the upload, then send the bytes; returns the id to attach it with."""
        created = self._request(
            "POST", "/v1/file_uploads", json={"filename": filename, "content_type": content_type}
        ).json()
        upload_id = str(created.get("id", ""))
        if not upload_id:
            raise NotionError(f"Notion did not return a file-upload id for {filename}")
        # The send step is multipart, not JSON, so the client's default Content-Type has to go:
        # httpx sets the multipart boundary itself and an inherited header would corrupt it.
        self._request(
            "POST",
            f"/v1/file_uploads/{upload_id}/send",
            files={"file": (filename, content, content_type)},
        )
        _log.info("file_uploaded", extra={"document": filename, "bytes": len(content)})
        return upload_id

    def download_file(self, url: str) -> bytes:
        """Fetch a Notion-hosted file from its signed URL.

        Deliberately a bare client: the URL is pre-signed object storage, and sending our Notion
        token to a third-party host would leak the credential for no benefit.
        """
        try:
            with httpx.Client(timeout=httpx.Timeout(60.0), follow_redirects=True) as plain:
                response = plain.get(url)
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Never the URL in the message: a Notion file URL is pre-signed, so it *is* read access
            # to that file, and this text reaches a log line and a Notion row.
            raise NotionError(
                f"could not download the attached file (HTTP {exc.response.status_code}); "
                "the link Notion issued may have expired — it will be re-read on the next pass"
            ) from exc
        except httpx.HTTPError as exc:
            raise NotionError(
                f"could not download the attached file: {type(exc).__name__}"
            ) from exc
        return response.content

    def close(self) -> None:
        self._client.close()


# -- pure JSON <-> model mapping (unit-tested without a network) ---------------
def rich_from_json(node: dict[str, Any]) -> RichText:
    text = node.get("plain_text")
    if text is None:
        text = (node.get("text") or {}).get("content", "")
    return RichText(
        text=text,
        annotations=Annotations.model_validate(node.get("annotations") or {}),
        href=node.get("href"),
    )


def rich_to_json(run: RichText) -> dict[str, Any]:
    text: dict[str, Any] = {"content": run.text}
    if run.href:
        text["link"] = {"url": run.href}
    return {
        "type": "text",
        "text": text,
        "annotations": run.annotations.model_dump(),
    }


def _rich_list(nodes: Any) -> list[RichText]:
    return [rich_from_json(n) for n in nodes] if isinstance(nodes, list) else []


def block_from_json(data: dict[str, Any]) -> Block:
    block_type = data.get("type", "")
    content = data.get(block_type) or {}
    meta: dict[str, object] = {}
    for key in ("color", "language", "checked"):
        if key in content:
            meta[key] = content[key]
    icon = content.get("icon")
    if isinstance(icon, dict) and icon.get("type") == "emoji":
        meta["icon"] = icon.get("emoji", "")
    if block_type == "table_row":
        cells = content.get("cells") or []
        meta["cells"] = [["".join(r.get("plain_text", "") for r in cell)] for cell in cells]
    return Block(
        id=data.get("id", ""),
        type=block_type,
        rich_text=_rich_list(content.get("rich_text")),
        has_children=data.get("has_children", False),
        meta=meta,
    )


def _comment_from_json(data: dict[str, Any], *, fallback_parent: str) -> Comment:
    parent = data.get("parent") or {}
    return Comment(
        id=data.get("id", ""),
        parent_id=parent.get("block_id") or parent.get("page_id") or fallback_parent,
        rich_text=_rich_list(data.get("rich_text")),
        author=str((data.get("created_by") or {}).get("id", "")),
        created_time=data.get("created_time", ""),
        discussion_id=data.get("discussion_id", ""),
    )


def _row_status(data: dict[str, Any]) -> str:
    """Read a queue row's Status select — the owner's decision, or empty if undecided."""
    prop = (data.get("properties") or {}).get("Status") or {}
    select = prop.get("select")
    return str(select.get("name", "")) if isinstance(select, dict) else ""


def page_title(data: dict[str, Any]) -> str:
    for prop in (data.get("properties") or {}).values():
        if isinstance(prop, dict) and prop.get("type") == "title":
            return "".join(r.get("plain_text", "") for r in prop.get("title", []))
    return ""
