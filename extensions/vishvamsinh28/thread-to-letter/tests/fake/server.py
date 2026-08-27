"""A small deterministic stand-in for the SuperDocs API.

Tests have to run without a live key, so something has to answer. This does — and it is
deliberately kept to the least it can be, because the logic worth testing in this build
is almost all offline: parsing a thread, checking that a quote really appears in it,
spotting a superseded commitment with no replacement, building a reply. Those tests
exercise real code and would fail for real reasons.

What this stand-in proves is only that the wiring holds: a chat turn goes out, a
document comes back, it is parsed and verified. It is not evidence about how the real
model classifies anything — see docs/LIVE-RESULTS.md for that, which is a live run.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import Body, FastAPI
from fastapi.responses import Response

app = FastAPI(title="fake-superdocs")

#: Rows the stand-in returns, keyed by a marker in the thread. Fixed, so a test asserting
#: on classification is asserting on the fixture and knows it.
_ROWS = [
    ("Calder and Vance", "Northwind", "deliver the schema mapping document",
     "21 March 2026", "firm", "7", "we will deliver the schema mapping document by 21 March 2026"),
    ("Calder and Vance", "Northwind", "deliver the schema mapping document",
     "14 March 2026", "superseded", "5",
     "Calder and Vance will deliver the schema mapping document to"),
    ("Northwind", "Calder and Vance", "pay the first invoice", "30 days of receipt",
     "firm", "6", "Northwind will pay the first invoice within 30 days of receipt"),
    ("Calder and Vance", "Northwind", "have the schema mapping done", "14 March 2026",
     "hedged", "3", "We should be able to have the schema mapping done by the 14th"),
    ("Sam", "Northwind", "get the test environment up", "next week", "second-hand", "3",
     "Sam mentioned they'd probably get the test environment up"),
    ("Nobody", "Nobody", "a commitment nobody made", "", "firm", "1",
     "this sentence is not anywhere in the thread"),
]

_TABLE = (
    "<table><tr><th>Party</th><th>Owes to</th><th>Obligation</th><th>Due</th>"
    "<th>Status</th><th>Source message</th><th>Exact quote</th></tr>"
    + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in _ROWS
    )
    + "</table>"
)

_NOTHING = "<p>No commitments were made in this thread.</p>"
_LETTER = (
    "<h1>[SENDER BLOCK]</h1><p>[DATE]</p><p>Subject: {subject}</p>"
    "<p>Dear [RECIPIENT NAME],</p>{body}"
    "<p>Please tell me if any of this is recorded incorrectly.</p>"
    "<p>Sincerely,</p><p>[SIGNATURE BLOCK]</p>"
)

_state: dict[str, str] = {}


@app.get("/v1/sessions")
def sessions() -> dict[str, Any]:
    return {"sessions": []}


@app.post("/v1/chat")
def chat(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    message = payload.get("message", "")
    session = payload.get("session_id", "")

    if "--- BEGIN THREAD ---" in message:
        thread = message.split("--- BEGIN THREAD ---", 1)[1]
        # An empty-ish thread gets the honest empty answer.
        html = _NOTHING if "schema mapping" not in thread else _TABLE
    else:
        # The letter turn: echo back exactly the commitments it was handed, so a test
        # can assert the letter contains what was confirmed and nothing else.
        listed = re.findall(r"^\d+\.\s+(.*)$", message, re.M)
        body = "".join(f"<p>{item}</p>" for item in listed) or (
            "<p>No commitments, dates or obligations were agreed by anyone.</p>"
        )
        subject = _subject(message)
        html = _LETTER.format(subject=subject, body=body)

    _state[session] = html
    return {
        "response": "done",
        "session_id": session,
        "document_changes": {"updated_html": html, "version_id": "v_1"},
        "usage": {"was_billable": True, "monthly_used": 1, "monthly_limit": 500,
                  "monthly_remaining": 499},
    }


@app.post("/v1/documents/export")
def export(payload: dict[str, Any] = Body(...)) -> Response:
    html = payload.get("html") or _state.get(payload.get("session_id", ""), "")
    fmt = payload.get("format", "docx")
    if fmt in ("html", "docx", "doc"):
        body = html.encode()
    else:
        text = re.sub(r"<[^>]+>", "\n", html)
        body = ("\n".join(l.strip() for l in text.splitlines() if l.strip()) + "\n").encode()
    return Response(content=body, media_type="application/octet-stream")


def _subject(message: str) -> str:
    match = re.search(r'titled "([^"]+)"', message)
    return match.group(1) if match else "(no subject)"


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FAKE_PORT", "8111")),
                log_level="warning")
