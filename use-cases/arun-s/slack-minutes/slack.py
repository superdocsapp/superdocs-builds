"""Minimal Slack client — fetch a thread's messages. Injectable transport so the whole
pipeline is testable without a Slack workspace or token. Live use needs a bot token with
`channels:history` (and `groups:history` for private channels)."""
from __future__ import annotations
import json
import os
import urllib.parse
import urllib.request

BASE = "https://slack.com/api"


class Slack:
    def __init__(self, token: str | None = None, transport=None):
        self.token = token or os.getenv("SLACK_TOKEN", "")
        self._t = transport   # callable(method, url, headers, params) -> (status, text)

    def _get(self, method: str, params: dict) -> dict:
        url = f"{BASE}/{method}?" + urllib.parse.urlencode(params)
        headers = {"Authorization": f"Bearer {self.token}"}
        if self._t:
            status, text = self._t("GET", url, headers, params)
        else:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
                status, text = r.status, r.read().decode("utf-8")
        data = json.loads(text)
        if not data.get("ok", False):
            raise RuntimeError(f"Slack error: {data.get('error', status)}")
        return data

    def thread(self, channel: str, thread_ts: str) -> list[dict]:
        """All messages in a thread, oldest first."""
        data = self._get("conversations.replies", {"channel": channel, "ts": thread_ts, "limit": 200})
        return [{"user": m.get("user", "?"), "text": m.get("text", ""), "ts": m.get("ts", "")}
                for m in data.get("messages", [])]
