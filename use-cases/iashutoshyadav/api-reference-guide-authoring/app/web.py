"""Chat-driven authoring app, two modes, per the task card. In-memory state for the same reason as the
sibling project: this is a single-operator authoring session, not a multi-user persistent system.
"""

from __future__ import annotations

import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.guide_generator import apply_guide_revision, generate_getting_started_guide, request_guide_revision
from app.markdown_roundtrip import RoundTripResult, round_trip_markdown
from app.superdocs_client import make_client

# Same real bug found in the sibling project (renewal-true-up-engine/app/web.py, 2026-08-19):
# python-dotenv doesn't load .env into os.environ on its own - without this call, a real
# SUPERDOCS_API_KEY set in .env was silently ignored with no error, just an unnoticed fake-client badge.
load_dotenv()

app = FastAPI(title="API-reference & Guide Authoring")
templates = Jinja2Templates(directory="app/templates")

_state: dict[str, object] = {
    "client": None,
    "roundtrip_result": None,
    "guide_result": None,
    "guide_session_id": None,
    "pending_revision": None,
}

_SAMPLE_MARKDOWN = """# API Reference: createWidget

Creates a new widget.

```python
import widgets

client = widgets.Client(api_key="...")
result = client.create_widget(name="my-widget")
```

![sequence diagram](./diagrams/create-widget-flow.png)
"""


def _get_client():
    if _state["client"] is None:
        _state["client"] = make_client(os.environ.get("SUPERDOCS_API_KEY"))
    return _state["client"]


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    using_fake = os.environ.get("SUPERDOCS_API_KEY", "") == ""
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "using_fake": using_fake,
            "sample_markdown": _SAMPLE_MARKDOWN,
            "roundtrip_result": _state["roundtrip_result"],
            "guide_result": _state["guide_result"],
            "pending_revision": _state["pending_revision"],
        },
    )


@app.post("/roundtrip", response_class=HTMLResponse)
def roundtrip(
    request: Request,
    markdown_text: str = Form(...),
    diagram_image: UploadFile | None = File(default=None),
):
    client = _get_client()
    uploaded_image = None
    if diagram_image is not None and diagram_image.filename:
        uploaded_image = (diagram_image.file.read(), diagram_image.content_type or "image/png")
    # Real bug, found live on 2026-08-20: a fixed session_id here meant every round-trip request for
    # the process's entire lifetime piled another upload into the SAME SuperDocs session. That session
    # eventually accumulated enough state to break - export_document started returning a real 404. Each
    # request is logically independent (a fresh markdown paste has nothing to do with the last one), so
    # each gets its own fresh session instead of sharing one that grows without bound.
    result: RoundTripResult = round_trip_markdown(
        client, markdown_text, session_id=f"roundtrip-{uuid.uuid4()}", uploaded_image=uploaded_image
    )
    _state["roundtrip_result"] = result
    return dashboard(request)


@app.post("/guide", response_class=HTMLResponse)
def guide(request: Request, feature_description: str = Form(...)):
    client = _get_client()
    # Same fix as roundtrip() above, same real failure mode: this is what actually 404'd first.
    session_id = f"guide-{uuid.uuid4()}"
    _state["guide_result"] = generate_getting_started_guide(client, feature_description, session_id=session_id)
    _state["guide_session_id"] = session_id
    _state["pending_revision"] = None
    return dashboard(request)


@app.post("/guide/revise", response_class=HTMLResponse)
def guide_revise(request: Request, revision_instruction: str = Form(...)):
    """The human-in-the-loop path (approve_change/chat_with_approval, the round's own stated four-call
    minimum contract) - real gap found auditing this build: both were implemented in the client but never
    called anywhere. Requesting a revision proposes a real edit and pauses for a person to review it,
    exactly like the sibling project's renewal amendments."""
    client = _get_client()
    session_id = _state["guide_session_id"]
    job = request_guide_revision(client, session_id, revision_instruction)
    if job.status == "awaiting_approval" and job.pending_changes:
        change = job.pending_changes[0]
        _state["pending_revision"] = {
            "job_id": job.job_id,
            "change_id": change.change_id,
            "old_html": change.old_html,
            "new_html": change.new_html,
            "ai_explanation": change.ai_explanation,
        }
    else:
        # Real finding, live on 2026-09-14: the same instruction against the same document did not
        # always produce a pending change - ask_every_time sometimes resolved and applied the edit
        # directly instead of pausing. Re-exporting here so that outcome isn't silently lost from
        # guide_result - a request that changed the document must be reflected, not dropped on the floor
        # just because it didn't take the review path this particular time.
        _state["guide_result"] = client.export_document(session_id, format="markdown")
    return dashboard(request)


@app.post("/guide/revise/decide", response_class=HTMLResponse)
def guide_revise_decide(request: Request, approved: str = Form(...), reason: str | None = Form(default=None)):
    client = _get_client()
    pending = _state["pending_revision"]
    session_id = _state["guide_session_id"]
    _state["guide_result"] = apply_guide_revision(
        client, session_id, pending["job_id"], pending["change_id"],
        approved=(approved == "true"), reason=reason or None,
    )
    _state["pending_revision"] = None
    return dashboard(request)
