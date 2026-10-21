"""Minimal Microsoft Graph OneNote client (delegated Notes.Read).

  GET /me/onenote/pages               -> list pages
  GET /me/onenote/pages/{id}/content  -> a page's absolutely-positioned HTML

`transport` is injectable — pass a fake to test the whole pipeline without a Microsoft
account or a token. In production it uses stdlib urllib with your bearer token; no SDK.
"""
from __future__ import annotations
import json
import os
import urllib.request

GRAPH = "https://graph.microsoft.com/v1.0"


class OneNote:
    def __init__(self, token: str | None = None, base: str = GRAPH, transport=None):
        self.token = token or os.getenv("GRAPH_TOKEN", "")
        self.base = base
        self._t = transport   # callable(method, url, headers) -> (status:int, body:str)

    def _get(self, path: str) -> str:
        url = self.base + path
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if self._t:
            status, body = self._t("GET", url, headers)
        else:  # user's app calling Microsoft Graph with the user's own token
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
                status, body = r.status, r.read().decode("utf-8")
        if status >= 400:
            raise RuntimeError(f"Graph {status}: {body[:200]}")
        return body

    def list_pages(self, top: int = 20) -> list[dict]:
        data = json.loads(self._get(f"/me/onenote/pages?$top={top}"))
        return [{"id": p["id"], "title": p.get("title", "(untitled)")} for p in data.get("value", [])]

    def page_html(self, page_id: str) -> str:
        # content is returned as text/html, not JSON
        return self._get(f"/me/onenote/pages/{page_id}/content")
