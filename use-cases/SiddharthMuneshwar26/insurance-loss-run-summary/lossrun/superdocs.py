"""The SuperDocs surface: upload, search, chat, approve, export.

Where the operations go, and why.

Searches cost operations and chat turns cost operations; uploads and exports do
not. A naive design that searched once per claim would spend 41 operations on
one account and still produce figures nobody could audit. So this build divides
the work by what each side is actually good at:

* **Figures are parsed, never searched.** Claim counts, incurred totals and loss
  ratios come from arithmetic over rows read out of the loss runs. That costs
  nothing and is reproducible.
* **Search is spent on the prose** — adjuster notes, the application, broker
  correspondence — where the contradictions live in sentences rather than
  columns, and where a keyword scan genuinely would miss them.
* **Chat writes the narrative around figures the app has already fixed**, and is
  told so explicitly, so the model is never the source of a number.

The API key is read from SUPERDOCS_API_KEY and is never an argument, never
logged, and never written to an output file.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field

BASE = os.environ.get("SUPERDOCS_BASE", "https://api.superdocs.app")

# Published pricing: exports and downloads are free, searches and chat are not.
# One place to change it if that changes.
OP_COST = {"upload": 0, "search": 1, "chat": 1, "approve": 0, "export": 0}


class ApiError(RuntimeError):
    pass


class SearchUnavailable(ApiError):
    """The dedicated search endpoint is not present on this deployment."""


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Ledger:
    cap: int
    spent: int = 0
    by_stage: dict[str, int] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    def charge(self, stage: str) -> None:
        cost = OP_COST.get(stage, 0)
        if cost and self.spent + cost > self.cap:
            raise BudgetExceeded(
                f"{stage!r} would take the run to {self.spent + cost} against a "
                f"cap of {self.cap}. Stopping before the spend, not after.")
        self.spent += cost
        self.by_stage[stage] = self.by_stage.get(stage, 0) + cost

    def record(self, stage: str, seconds: float) -> None:
        self.timings[stage] = round(self.timings.get(stage, 0.0) + seconds, 2)


class SuperDocsClient:
    def __init__(self, ledger: Ledger, timeout_s: float = 600.0,
                 poll_interval: float = 3.0):
        key = os.environ.get("SUPERDOCS_API_KEY")
        if not key:
            raise ApiError(
                "SUPERDOCS_API_KEY is not set. Export it in your shell; this "
                "build never takes a key as an argument.")
        self._key = key
        self.ledger = ledger
        self.timeout_s = timeout_s
        self.poll_interval = poll_interval

    @property
    def _json(self) -> dict:
        return {"Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json"}

    @property
    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self._key}"}

    @staticmethod
    def _redact(text: str) -> str:
        return re.sub(r"sk_[A-Za-z0-9_\-]{4,}", "sk_[REDACTED]", text or "")

    def _check(self, resp, what: str):
        if resp.status_code >= 400:
            raise ApiError(f"{what}: HTTP {resp.status_code} "
                           f"{self._redact(resp.text)[:400]}")
        return resp

    # -- the calls ---------------------------------------------------------
    def upload(self, path: str, session_id: str) -> str:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("upload")
        with open(path, "rb") as fh:
            r = requests.post(
                f"{BASE}/v1/documents/upload", headers=self._auth,
                files={"file": (os.path.basename(path), fh)},
                data={"session_id": session_id}, timeout=self.timeout_s)
        self._check(r, "upload")
        self.ledger.record("upload", time.monotonic() - t0)
        html = r.json().get("html")
        if not html:
            raise ApiError("upload returned no html")
        return html

    def search(self, session_id: str, query: str, limit: int = 8) -> list[dict]:
        """Semantic search across the documents uploaded to this session.

        A dedicated search endpoint returned 404 on the live API when this was
        written, so `retrieve` below is the path actually used. This method is
        kept because the capability is real and may be exposed directly later;
        it raises SearchUnavailable on 404 rather than pretending it worked.
        """
        import requests
        t0 = time.monotonic()
        self.ledger.charge("search")
        r = requests.post(
            f"{BASE}/v1/search", headers=self._json,
            json={"session_id": session_id, "query": query, "limit": limit},
            timeout=self.timeout_s)
        if r.status_code == 404:
            raise SearchUnavailable(
                "no dedicated search endpoint on this deployment; "
                "cross-document retrieval runs through the chat surface")
        self._check(r, "search")
        self.ledger.record("search", time.monotonic() - t0)
        body = r.json()
        hits = body.get("results") or body.get("matches") or []
        out = []
        for h in hits:
            out.append({
                "document": h.get("document") or h.get("filename") or "",
                "text": h.get("text") or h.get("content") or "",
                "score": h.get("score"),
            })
        return out

    def retrieve(self, session_id: str, questions: list[str]) -> list[dict]:
        """Ask the attached documents and parse a JSON reply.

        NOT used by the review pipeline. It asked for chat text and looked for
        it in the proposed-changes payload, which carries document edits; the
        reply was never there to find. The pipeline now has the agent write its
        answer into the document instead, which is the supported path and costs
        one operation rather than two. Kept, unused, because the JSON-reply
        shape is worth having if a chat-reply field is exposed later.
        """
        prompt = (
            "Search the documents attached to this session and answer each "
            "question below from them. Reply with JSON only, no prose and no "
            "code fences: a list of objects with keys \"question\", "
            "\"document\", \"quote\". Quote at most two sentences verbatim "
            "from the source. If nothing in the attached documents answers a "
            "question, return an object for it with \"document\": null. Do "
            "not infer, summarise across documents, or state anything the "
            "attached text does not say.\n\n"
            + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
        )
        job = self.edit(session_id, "<p></p>", prompt)
        raw = ""
        for c in job.get("pending") or []:
            content = c.get("content")
            if isinstance(content, dict):
                raw = content.get("text") or content.get("message") or ""
            elif isinstance(content, str):
                raw = content
            if raw:
                break
        return _parse_retrieval(raw)

    def edit(self, session_id: str, document_html: str, instruction: str) -> dict:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("chat")
        r = requests.post(
            f"{BASE}/v1/chat/async", headers=self._json,
            json={"message": instruction, "session_id": session_id,
                  "document_html": document_html,
                  "approval_mode": "ask_every_time"},
            timeout=self.timeout_s)
        self._check(r, "chat/async")
        job_id = r.json()["job_id"]

        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            j = self._check(requests.get(f"{BASE}/v1/jobs/{job_id}",
                                         headers=self._json,
                                         timeout=self.timeout_s), "jobs/get")
            job = j.json()
            status = job.get("status")
            if status in ("awaiting_approval", "completed"):
                self.ledger.record("chat", time.monotonic() - t0)
                return {"job_id": job_id, "status": status,
                        "pending": self._pending(job)}
            if status in ("failed", "cancelled"):
                raise ApiError(f"job {status}: "
                               f"{self._redact(str(job.get('error')))[:300]}")
            time.sleep(self.poll_interval)
        raise ApiError(f"job {job_id} did not finish within {self.timeout_s:.0f}s. "
                       f"A long silence is normal on this API, so this is a "
                       f"timeout, not a proven failure.")

    @staticmethod
    def _pending(job: dict) -> list[dict]:
        """Proposed-change content arrives JSON-encoded and needs a second
        parse; the final result is already an object. Missing this is the most
        common reason integrators see empty diffs."""
        out = []
        for c in (job.get("metadata") or {}).get("pending_changes") or []:
            c = dict(c)
            if isinstance(c.get("content"), str):
                try:
                    c["content"] = json.loads(c["content"])
                except (ValueError, TypeError):
                    c["content_parse_failed"] = True
            out.append(c)
        return out

    def approve(self, session_id: str, job_id: str, changes: list[dict]) -> dict:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("approve")
        r = requests.post(
            f"{BASE}/v1/chat/{session_id}/approve", headers=self._json,
            json={"job_id": job_id, "approved": True,
                  "changes": [{"change_id": c.get("change_id"), "approved": True}
                              for c in changes]},
            timeout=self.timeout_s)
        self._check(r, "approve")
        self.ledger.record("approve", time.monotonic() - t0)
        return r.json()

    def export(self, session_id: str, out_path: str, fmt: str = "docx") -> str:
        import requests
        t0 = time.monotonic()
        self.ledger.charge("export")
        r = requests.post(f"{BASE}/v1/documents/export", headers=self._json,
                          json={"session_id": session_id, "format": fmt},
                          timeout=self.timeout_s)
        self._check(r, "export")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "wb") as fh:
            fh.write(r.content)
        self.ledger.record("export", time.monotonic() - t0)
        return out_path


class FakeClient:
    """Offline stand-in. Returns nothing it was not given, so a test that
    passes against it is testing this build's own logic and never the API's."""

    def __init__(self, ledger: Ledger, corpus_text: dict[str, str] | None = None):
        self.ledger = ledger
        self.corpus_text = corpus_text or {}
        self._sessions: dict[str, str] = {}

    def upload(self, path: str, session_id: str) -> str:
        self.ledger.charge("upload")
        html = f"<p>{os.path.basename(path)}</p>"
        self._sessions[session_id] = html
        return html

    def search(self, session_id: str, query: str, limit: int = 8) -> list[dict]:
        self.ledger.charge("search")
        return self._keyword(query, limit)

    def _keyword(self, query: str, limit: int = 8) -> list[dict]:
        """Keyword matching over the local text. Weaker than the real thing on
        purpose: if a result only appears live, the difference is visible
        rather than hidden."""
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 3]
        hits = []
        for name, text in self.corpus_text.items():
            low = text.lower()
            score = sum(low.count(t) for t in terms)
            if score:
                idx = min((low.find(t) for t in terms if t in low), default=0)
                hits.append({"document": name, "score": score,
                             "text": text[max(0, idx - 200): idx + 400]})
        hits.sort(key=lambda h: -h["score"])
        return hits[:limit]

    def retrieve(self, session_id: str, questions: list[str]) -> list[dict]:
        self.ledger.charge("chat")
        out = []
        for q in questions:
            hits = self._keyword(q, limit=1)
            out.append({"question": q,
                        "document": hits[0]["document"] if hits else None,
                        "quote": hits[0]["text"][:300] if hits else ""})
        return out

    def edit(self, session_id: str, document_html: str, instruction: str) -> dict:
        """Fills the placeholder by keyword, so a dry run shows the real shape
        of the output. Deliberately weaker than the live path: if a point only
        surfaces against the real API, that difference stays visible."""
        self.ledger.charge("chat")
        if "[[CORRESPONDENCE]]" in document_html:
            lines = []
            for q in re.findall(r"^   - (.+)$", instruction, re.M):
                hits = self._keyword(q, limit=1)
                if hits:
                    quote = " ".join(hits[0]["text"].split())[:200]
                    lines.append(f"<p><i>{hits[0]['document']}</i> \u2014 {quote}</p>")
                else:
                    lines.append(f"<p>Nothing in the attached documents "
                                 f"addresses: {q}</p>")
            document_html = document_html.replace(
                "<p>[[CORRESPONDENCE]]</p>", "".join(lines) or
                "<p>Nothing in the attached documents addresses these "
                "points.</p>")
        self._sessions[session_id] = document_html
        return {"job_id": f"fake-{session_id}", "status": "awaiting_approval",
                "pending": [{"change_id": "c1",
                             "content": json.dumps({"instruction": instruction})}]}

    def approve(self, session_id: str, job_id: str, changes: list[dict]) -> dict:
        self.ledger.charge("approve")
        return {"status": "applied", "applied": len(changes)}

    def export(self, session_id: str, out_path: str, fmt: str = "docx") -> str:
        self.ledger.charge("export")
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(self._sessions.get(session_id, ""))
        return out_path


def _parse_retrieval(raw: str) -> list[dict]:
    """Parse the retrieval reply, tolerating fences and surrounding prose.

    Returns [] rather than raising when the reply is not usable: a retrieval
    that could not be read is an absent section, not a corrupt document.
    """
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict) and item.get("document"):
            out.append({"document": str(item.get("document")),
                        "text": str(item.get("quote") or ""),
                        "question": str(item.get("question") or "")})
    return out
