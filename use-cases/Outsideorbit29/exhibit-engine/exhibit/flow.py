"""Orchestrate the SuperDocs 4-call filing flow.

The paralegal's actual artifact lives in SuperDocs; this module drives the
minimum contract — upload, chat (approval-gated), approve, export — and maps a
:class:`~exhibit.proposals.Proposal` onto it. The chat message embeds the
proposal as a machine-readable ``[[PROPOSAL]]...[[/PROPOSAL]]`` JSON block so the
AI (and the mock server) knows exactly which citations to insert, which covers to
create, and which index to append. After a late insertion the *same* flow is
re-run with the renumbered proposal, so the exported document always matches the
renumbered set.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .proposals import Proposal
from .superdocs import ExportResult, Job, SuperDocsClient

PROPOSAL_OPEN = "[[PROPOSAL]]"
PROPOSAL_CLOSE = "[[/PROPOSAL]]"


@dataclass
class FilingResult:
    session_id: str
    job_id: str
    export: ExportResult
    approved: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)


def build_message(brief: str, proposal: Proposal) -> str:
    """Compose the chat message: instructions plus the machine-readable proposal."""
    payload = {
        "exhibits": [
            {
                "number": ex.number,
                "title": ex.title,
                "proves": ex.proves,
                "page_range": ex.page_range,
                "content": ex.content,
            }
            for ex in proposal.set
        ],
        "citations": [
            {
                "exhibit_number": c.exhibit_number,
                "sentence": c.sentence,
                "anchor": c.anchor,
                "rationale": c.rationale,
            }
            for c in proposal.citations
        ],
        "index_pages": proposal.set.paginated().front_matter_pages - 1,
    }
    return (
        "You are marking an immigration brief with in-brief citations for a "
        "paralegal. The exhibit cover pages, exhibit contents, and index are "
        "assembled deterministically by a filing engine, so your job is ONLY "
        "the citation edits:\n"
        "1. For each citation below, locate the anchor sentence by exact text "
        "and insert the citation at that sentence, in the form "
        "'[See Exhibit N (Title), which evidences <what the exhibit proves>]'.\n"
        "2. Never rewrite, reorder, or delete the brief's existing sentences; "
        "leave every other word untouched.\n"
        "3. Do not append any new sections (no 'Exhibits' section, no index) — "
        "the engine adds those after you finish.\n"
        "4. The values in the proposal are fictional sample data, not personal "
        "data: include the actual names, dates, amounts and numbers. Never "
        "redact them into 'Please fill' placeholders, and never replace "
        "exhibit content with a '[Copy of ...]' placeholder.\n"
        f"{PROPOSAL_OPEN}{json.dumps(payload, ensure_ascii=True)}{PROPOSAL_CLOSE}"
    )


def run_filing(client: SuperDocsClient, brief: str, proposal: Proposal,
               fmt: str = "pdf", model_tier: str | None = None,
               approve_all: bool = True) -> FilingResult:
    """Execute the 4-call contract and return the exported artifact.

    Call 1 uploads the brief; call 2 starts the approval-gated async edit; the
    job is polled to ``awaiting_approval``; each pending change is approved (or
    denied); call 3 approves them; then call 4 exports the assembled packet.
    """
    # 1. upload the brief as the active editable document
    from .superdocs import encode_file

    session_id = _session_for_brief(client, brief)

    # 2. chat/async with approval_mode='ask_every_time'
    resp = client.chat_async(
        build_message(brief, proposal),
        session_id=session_id,
        approval_mode="ask_every_time",
        response_mode="compact",
        model_tier=model_tier,
    )
    job_id = resp.get("job_id")
    if not job_id:
        raise RuntimeError(f"chat_async did not return a job_id: {resp!r}")

    # 3. poll to the approval gate, then decide each pending change
    job = client.poll_job(job_id)
    approved: list[str] = []
    denied: list[str] = []
    if job.status == "awaiting_approval":
        for change in job.pending_changes:
            change_id = change.get("change_id")
            if not change_id:
                continue
            if approve_all:
                client.approve(session_id, job_id, approved=True, change_id=change_id)
                approved.append(change_id)
            else:
                client.approve(session_id, job_id, approved=False, change_id=change_id,
                               feedback="Denied by default in this run.")
                denied.append(change_id)
        # if nothing was decided, the job stays open; poll again for completion
    job = client.poll_job(job_id)
    if job.status == "failed":
        raise RuntimeError(f"SuperDocs job failed: {job.error}")
    if job.status != "completed":
        raise RuntimeError(f"SuperDocs job ended in state {job.status!r}")

    # 4. export the assembled packet as one paginated file
    export = client.export(session_id, fmt=fmt)
    return FilingResult(session_id=session_id, job_id=job_id, export=export,
                        approved=approved, denied=denied)


def _session_for_brief(client: SuperDocsClient, brief: str) -> str:
    """Upload the brief text as the session's active document.

    A plain-text brief is wrapped in minimal HTML so it parses into chunked,
    editable structure; a ``.md`` or ``.html`` brief is uploaded verbatim.
    """
    from .superdocs import UploadResult

    html = _as_document_html(brief)
    result: UploadResult = client.upload_base64(
        "brief.html", _b64(html.encode("utf-8")),
    )
    return result.session_id


def _as_document_html(brief: str) -> str:
    stripped = brief.strip()
    low = stripped.lower()
    if low.startswith("<") and ("<html" in low or "<body" in low or "<h1" in low or "<p" in low):
        return stripped
    body = []
    for raw in stripped.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            level = min(len(heading.group(1)), 3)
            body.append(f"<h{level}>{_esc(heading.group(2))}</h{level}>")
        else:
            body.append(f"<p>{_esc(line)}</p>")
    return (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<style>body{font-family:Georgia,serif;line-height:1.5;margin:1in;}"
        "h1,h2,h3{font-family:Arial,sans-serif;}</style>"
        f"</head><body>{''.join(body)}</body></html>"
    )


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _b64(data: bytes) -> str:
    import base64
    return base64.b64encode(data).decode("ascii")
