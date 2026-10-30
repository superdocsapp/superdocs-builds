#!/usr/bin/env python3
"""Drive the live SuperDocs service and record each scenario to a cassette.

Each scenario is independently runnable and re-runnable, so a long recording session
survives an interruption without losing what it already captured:

    python scripts/record_scenarios.py --list
    python scripts/record_scenarios.py styled-document
    python scripts/record_scenarios.py --free-only

Scenarios are ordered cheapest-first on purpose. The free ones settle open findings and
build the document the billable ones need, so a budget stop never leaves the corpus half
recorded.

Costs real operations. The recorder enforces a hard budget and stops rather than grind.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sdmock.cassette import Cassette  # noqa: E402
from sdmock.record import BudgetExceeded, Recorder  # noqa: E402

CORPUS = ROOT / "corpus"
CASSETTES = ROOT / "cassettes"
SPEC_PIN = "ac0d44c3d031fd0e338e7e78839162904ee69e79"

# Session ids are fixed strings so a re-run lands in the same place and the recorded
# paths stay stable between recordings (B-008: the client chooses these).
S_STYLED = "sdmock-styled-001"
S_REVIEW = "sdmock-review-001"
S_LARGE = "sdmock-large-001"
S_CAPACITY = "sdmock-capacity-001"


def save(cassette: Cassette) -> None:
    path = cassette.save(CASSETTES)
    print(f"  -> {path.relative_to(ROOT)}  "
          f"({len(cassette.interactions)} interactions, "
          f"{cassette.billable_count} billable)")


# --------------------------------------------------------------------------- scenarios


def rec_format_probes(r: Recorder) -> None:
    """FREE. Settles F-003: are .doc and .odt accepted or refused?

    /concepts/documents lists DOC and ODT as supported formats; /errors/error-codes says
    a legacy .doc is a 415 and never mentions ODT. One upload each decides it.
    """
    c = r.new_cassette(
        "unsupported-format",
        "Upload refusals for a legacy .doc and an .odt, settling the contradiction "
        "between the supported-formats list and the documented 415 message.",
        covers=["B-068", "B-069", "B-077"],
    )
    for name in ("legacy-format-probe.doc", "rate-card.odt"):
        path = CORPUS / name
        with path.open("rb") as fh:
            r.call(
                c, "POST", "/v1/documents/upload",
                files={"file": (name, fh, "application/octet-stream")},
                data={"session_id": f"sdmock-probe-{path.suffix.lstrip('.')}"},
                note=f"format probe: {path.suffix}",
            )
    save(c)


def rec_styled_document(r: Recorder) -> None:
    """FREE (uploads are not billed, B-089). The 'styled document with sections'."""
    c = r.new_cassette(
        "styled-document",
        "Upload and parse of a heavily styled 30+ section contract: numbered clauses, "
        "two tables with merged header cells and alternating shading, running header "
        "and footer, A4 page geometry.",
        covers=["B-077", "B-078", "B-080", "B-017", "B-089"],
    )
    path = CORPUS / "master-services-agreement.docx"
    with path.open("rb") as fh:
        response = r.call(
            c, "POST", "/v1/documents/upload",
            files={"file": (path.name, fh,
                            "application/vnd.openxmlformats-officedocument."
                            "wordprocessingml.document")},
            data={"session_id": S_STYLED},
            note="styled DOCX -> ProcessDocumentResponse",
        )
    body = response.json() if response.status_code < 400 else {}
    print(f"    chunks_count={body.get('chunks_count')} "
          f"parse_mode={body.get('parse_mode')} "
          f"page_setup={'present' if body.get('page_setup') else 'null'}")
    save(c)


def rec_export(r: Recorder) -> None:
    """FREE (exports are not billed, B-089). Settles F-002: JSON or binary?"""
    c = r.new_cassette(
        "export-docx",
        "Export of the session document. Records the actual media type and headers of "
        "the export 200, settling whether it is a binary download or JSON.",
        covers=["B-081", "B-082", "B-083", "B-084", "B-087", "B-089", "B-111"],
    )
    response = r.call(
        c, "POST", "/v1/documents/export",
        json_body={"session_id": S_STYLED, "format": "docx",
                   "options": {"filename": "agreement-export", "paper_size": "A4"}},
        note="export from session -> settles F-002",
    )
    print(f"    content-type: {response.headers.get('content-type')!r}")
    print(f"    content-disposition: {response.headers.get('content-disposition')!r}")
    print(f"    x-export-warnings: {response.headers.get('x-export-warnings')!r}")
    print(f"    body starts: {response.content[:16]!r}")

    # Export before anything is loaded: a 404 with an actionable message, and one of
    # the first errors an integrator meets while wiring up the four-call contract.
    r.call(
        c, "POST", "/v1/documents/export",
        json_body={"session_id": "sdmock-empty-session-001", "format": "docx"},
        note="export from a session holding no document -> documented 404 (B-111)",
    )

    # A second export in a format that is out of the enum, for the documented 422.
    r.call(
        c, "POST", "/v1/documents/export",
        json_body={"session_id": S_STYLED, "format": "pages"},
        note="out-of-enum format -> documented 422 (B-076)",
    )
    save(c)


def rec_capacity_refusal(r: Recorder) -> None:
    """FREE. The capacity refusal: a document past the documented section limit.

    Run once. The point is the refusal, and there is no reason to push a large payload
    at a live service more than once to observe a documented behaviour.
    """
    c = r.new_cassette(
        "capacity-refusal",
        "A document past the documented 25,000-sections-per-document scale limit, "
        "producing the structured 413 that carries limit_expandable: true, plus the "
        "documented recovery path.",
        covers=["B-073", "B-074", "B-070"],
    )
    path = CORPUS / "oversize-consignment-register.html"
    with path.open("rb") as fh:
        response = r.call(
            c, "POST", "/v1/documents/upload",
            files={"file": (path.name, fh, "text/html")},
            data={"session_id": S_CAPACITY},
            note="oversize document -> capacity refusal",
        )
    print(f"    status={response.status_code} body={response.text[:400]}")
    save(c)


def rec_proposed_change_batch(r: Recorder) -> None:
    """BILLABLE (~1-2 ops). The review scenario: propose, stream, approve, deny."""
    c = r.new_cassette(
        "proposed-change-batch",
        "A review-mode edit: chat_async with approval_mode ask_every_time, the SSE "
        "stream carrying proposed_change_batch with its double-encoded content, the "
        "job sitting in awaiting_approval, and a mixed approve/deny decision.",
        covers=["B-023", "B-024", "B-025", "B-026", "B-040", "B-041", "B-042",
                "B-044", "B-045", "B-046", "B-051", "B-052", "B-053", "B-055",
                "B-058", "B-060"],
    )
    # Load a small document into a fresh session so the edit is cheap and bounded.
    small = (
        '<h1>Supplier Code of Conduct</h1>'
        '<p>Suppliers shall comply with all applicable laws.</p>'
        '<p>Suppliers shall maintain accurate records for three years.</p>'
        '<p>Suppliers shall not engage in forced labour of any kind.</p>'
        '<p>Suppliers shall report breaches within ten days.</p>'
    )
    started = r.call(
        c, "POST", "/v1/chat/async",
        json_body={
            "message": "Tighten the wording of the record-keeping clause and the "
                       "breach-reporting clause. Change nothing else.",
            "session_id": S_REVIEW,
            "document_html": small,
            "approval_mode": "ask_every_time",
            "model_tier": "core",
        },
        note="start a review-mode edit",
        expect_billable=True,
    )
    job = started.json()
    job_id = job.get("job_id")
    print(f"    job_id={job_id} status={job.get('status')}")

    # Capture the stream in the same turn -- this is where proposed_change_batch lands.
    # In review mode the stream pauses at the proposal and emits nothing further until
    # a decision arrives, so the capture stops there rather than idling to the cap.
    frames = r.stream(
        c, S_REVIEW, job_id, max_seconds=300,
        stop_on=frozenset({"proposed_change_batch", "final", "error"}),
        note="SSE for the review turn, up to the proposal",
    )
    kinds = [f.event for f in frames]
    print(f"    events: {kinds}")

    # Poll the job so the polling shape is recorded alongside the streaming shape.
    pending: list[dict] = []
    for _ in range(60):
        polled = r.call(c, "GET", f"/v1/jobs/{job_id}", note="poll for review state")
        body = polled.json()
        status = body.get("status")
        if status == "awaiting_approval":
            meta = body.get("metadata") or {}
            pending = meta.get("pending_changes") or []
            print(f"    awaiting_kind={meta.get('awaiting_kind')!r} "
                  f"pending={len(pending)}")
            break
        if status in {"completed", "failed", "cancelled"}:
            print(f"    job ended as {status} without pausing for review")
            break
        time.sleep(3)

    if not pending:
        save(c)
        return

    # The documented 422 first, while there is a live job to aim it at (B-041).
    r.call(
        c, "POST", f"/v1/chat/{S_REVIEW}/approve",
        json_body={"job_id": job_id,
                   "changes": [{"change_id": pending[0]["change_id"]}]},
        note="batch without top-level approved -> documented 422",
    )

    # A mixed decision, so the cassette proves a denial is honoured alongside an
    # approval rather than only recording a happy 'approve all'. Denying with feedback
    # is documented to open another review round (B-048), so this loops rather than
    # assuming one pass -- which is exactly the shape an integrator has to write.
    denied_once = False
    for round_index in range(4):
        decisions = [{"change_id": pending[0]["change_id"], "approved": True}]
        if len(pending) > 1 and not denied_once:
            decisions.append({"change_id": pending[1]["change_id"], "approved": False,
                              "feedback": "Keep the original ten-day wording."})
            denied_once = True
        for change in pending[len(decisions):]:
            decisions.append({"change_id": change["change_id"], "approved": True})

        r.call(
            c, "POST", f"/v1/chat/{S_REVIEW}/approve",
            json_body={"job_id": job_id, "approved": True, "changes": decisions},
            note=f"decision round {round_index + 1}"
                 + (" (one approved, one denied with feedback)" if round_index == 0 else ""),
        )

        pending = []
        for _ in range(60):
            polled = r.call(c, "GET", f"/v1/jobs/{job_id}",
                            note=f"poll after decision round {round_index + 1}")
            body = polled.json()
            status = body.get("status")
            if status == "awaiting_approval":
                pending = (body.get("metadata") or {}).get("pending_changes") or []
                if pending:
                    print(f"    another review round: {len(pending)} pending")
                    break
            elif status in {"completed", "failed", "cancelled"}:
                usage = ((body.get("result") or {}).get("usage")) or {}
                print(f"    job {status}; ops_charged={usage.get('ops_charged')} "
                      f"bucket={usage.get('bucket_used')} "
                      f"billable={usage.get('was_billable')}")
                break
            time.sleep(3)
        if not pending:
            break

    # Reconnect to the stream with last_sequence set, which is the documented resume:
    # only newer events replay (B-056). Recording it is the only way the mock can serve
    # it faithfully.
    highest = max((f.sequence or 0) for f in frames) if frames else 0
    r.stream(c, S_REVIEW, job_id, max_seconds=180,
             last_sequence=highest,
             note=f"stream resumed from last_sequence={highest} (B-056)")
    save(c)


def rec_mcp_journey(r: Recorder) -> None:
    """BILLABLE (~1 op). The four-call contract over MCP rather than REST."""
    c = r.new_cassette(
        "mcp-journey",
        "The MCP Streamable HTTP surface: protocol handshake with its instructions "
        "field, the full 38-tool / 4-prompt roster, and the two non-billable tools an "
        "agent calls first (health, get_account_status). Editing over MCP is covered "
        "by the REST cassettes through the shared replay core, not duplicated here.",
        covers=["B-006", "B-094", "B-095", "B-096", "B-098"],
    )
    init = r.mcp(c, "initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "sdmock-recorder", "version": "0.1.0"},
    }, rpc_id=1, note="handshake")
    session = (init.get("result") or {}).get("_session_id")
    print(f"    server={((init.get('result') or {}).get('serverInfo') or {}).get('version')}")

    r.mcp(c, "tools/list", {}, rpc_id=2, session_id=session, note="tool surface")
    r.mcp(c, "tools/call", {
        "name": "health",
        "arguments": {},
    }, rpc_id=3, session_id=session, note="health tool (non-billable)")
    r.mcp(c, "tools/call", {
        "name": "get_account_status",
        "arguments": {},
    }, rpc_id=4, session_id=session, note="account status (non-billable, B-091)")
    save(c)


def rec_large_multi_section_edit(r: Recorder) -> None:
    """BILLABLE (~16 ops). A whole-document edit across 400 sections, in compact mode.

    An honest attempt at the real thing rather than a hand-written shape. If the service
    finishes in one turn instead of pausing, that is recorded as-is and the continue
    prompt is synthesised from the documented shape, labelled as such -- never dressed up
    as a recording.
    """
    c = r.new_cassette(
        "large-multi-section-edit",
        "A whole-document edit across a 400-section register in compact response mode: "
        "sixteen operations in one turn, per-section chunk_diffs instead of full HTML, "
        "and the surgical-precision summary the service returns.",
        covers=["B-016", "B-018", "B-020", "B-025", "B-026", "B-027", "B-029",
                "B-109", "B-110"],
    )
    html = (CORPUS / "large-consignment-register.html").read_text(encoding="utf-8")
    r.check_budget(16)

    started = r.call(
        c, "POST", "/v1/chat/async",
        json_body={
            "message": "In every consignment entry, replace 'POD on file' with "
                       "'proof of delivery retained'. Change nothing else.",
            "session_id": S_LARGE,
            "document_html": html,
            "approval_mode": "approve_all",
            "model_tier": "core",
            "response_mode": "compact",
        },
        note="whole-document edit over 400 sections",
        expect_billable=True,
    )
    job_id = started.json().get("job_id")
    print(f"    job_id={job_id}")

    paused = False
    for attempt in range(240):  # up to ~20 minutes, well inside the 30-minute cap
        # Every poll goes through the recorder, so every one gets the transport retry.
        # Only a few are kept in the cassette -- a replay needs the state transitions,
        # not two hundred identical in_progress rows.
        polled = r.call(c, "GET", f"/v1/jobs/{job_id}", note=f"poll {attempt + 1}")
        if attempt % 15 != 0:
            c.interactions.pop()
        body = polled.json()
        status = body.get("status")
        meta = body.get("metadata") or {}
        if status == "awaiting_approval" and meta.get("awaiting_kind") == "continue_prompt":
            prompt = meta.get("continue_prompt") or {}
            print(f"    PAUSED: {prompt.get('done')}/{prompt.get('total')} done, "
                  f"{prompt.get('remaining')} remaining")
            paused = True
            r.call(c, "GET", f"/v1/jobs/{job_id}", note="the continue_prompt pause")
            # Calling /approve on a continue pause is documented to be a 409 (B-036).
            r.call(c, "POST", f"/v1/chat/{S_LARGE}/approve",
                   json_body={"job_id": job_id, "approved": True},
                   note="approve on a continue pause -> documented 409")
            r.call(c, "POST", f"/v1/chat/{S_LARGE}/continue",
                   json_body={"job_id": job_id, "continue": False},
                   note="stop here and keep the work already applied (B-037)")
            break
        if status in {"completed", "failed", "cancelled"}:
            usage = ((body.get("result") or {}).get("usage")) or {}
            print(f"    finished as {status} without pausing "
                  f"(ops_charged={usage.get('ops_charged')})")
            r.call(c, "GET", f"/v1/jobs/{job_id}", note="terminal state")
            break
        time.sleep(5)

    c.description += (
        "  RECORDED: the turn paused as documented."
        if paused else
        "  NOTE: this turn completed without pausing, so no continue_prompt was "
        "observed. The continue-prompt scenario is synthesised separately and labelled."
    )
    save(c)


def rec_large_file_upload(r: Recorder) -> None:
    """FREE. The pre-signed upload path, for documents too big for a request body.

    The documented flow for anything over 20 MB, and the one the round asks for -- large
    files through the upload path rather than through memory. It is also the only route
    that declares ProcessDocumentResponse, so recording it gives the contract suite a
    real schema to check rather than the empty one the multipart route publishes.
    """
    c = r.new_cassette(
        "large-file-upload",
        "The pre-signed upload flow: request a URL, PUT the bytes straight to storage, "
        "then parse by upload_id. Keeps large documents out of the request body, and "
        "returns the only response on the surface that declares ProcessDocumentResponse.",
        covers=["B-077", "B-078", "B-080", "B-085", "B-086", "B-089", "B-099"],
    )
    source = CORPUS / "master-services-agreement.docx"
    payload = source.read_bytes()
    docx = ("application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document")

    granted = r.call(
        c, "POST", "/v1/uploads",
        json_body={"filename": source.name, "content_type": docx,
                   "size_bytes": len(payload), "purpose": "document"},
        note="request a pre-signed PUT URL (valid 5 minutes, B-086)",
    ).json()

    # The PUT goes straight to object storage, not to SuperDocs, so it is deliberately
    # not recorded: the URL is signed, single-use and scrubbed, and replaying somebody
    # else's storage endpoint is not something a mock should ever do.
    put = r.client.put(granted["upload_url"], content=payload,
                       headers={"Content-Type": docx})
    print(f"    PUT    (object storage, not recorded)               -> {put.status_code}")

    r.call(
        c, "POST", f"/v1/uploads/{granted['upload_id']}/process",
        json_body={"upload_id": granted["upload_id"], "filename": source.name,
                   "session_id": "sdmock-process-001", "parse_mode": "document"},
        note="parse by upload_id -> ProcessDocumentResponse",
    )
    save(c)


def rec_account_status(r: Recorder) -> None:
    """FREE. What an agent calls to decide whether it can afford the work.

    Also the evidence for F-001: whoami reports the tier bucket only, while the
    promotions endpoint shows the balance it omits. Recording both side by side puts the
    discrepancy in the fixtures rather than only in a finding.
    """
    c = r.new_cassette(
        "account-status",
        "Account and quota calls: whoami (what an agent budgets from), the promotions "
        "balance it omits, and the documented 401 from the web-app-only usage endpoint.",
        covers=["B-005", "B-092", "B-093"],
    )
    r.call(c, "GET", "/v1/agents/whoami",
           note="the call agents are told to budget from -- tier bucket only (F-001)")
    r.call(c, "GET", "/v1/users/me/promotions",
           note="the promo balance whoami leaves out")
    r.call(c, "GET", "/v1/users/me/usage",
           note="web-app-only: rejects sk_ keys with a clear 401 (B-005)")
    save(c)


SCENARIOS: dict[str, tuple[str, bool, object]] = {
    "unsupported-format": ("free", False, rec_format_probes),
    "styled-document": ("free", False, rec_styled_document),
    "export-docx": ("free", False, rec_export),
    "capacity-refusal": ("free", False, rec_capacity_refusal),
    "large-file-upload": ("free", False, rec_large_file_upload),
    "account-status": ("free", False, rec_account_status),
    "proposed-change-batch": ("billable", True, rec_proposed_change_batch),
    "mcp-journey": ("billable", True, rec_mcp_journey),
    "large-multi-section-edit": ("billable", True, rec_large_multi_section_edit),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenarios", nargs="*", help="scenario ids to record")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--free-only", action="store_true",
                    help="record only the scenarios that spend no operations")
    ap.add_argument("--budget", type=int, default=50)
    args = ap.parse_args()

    if args.list:
        for name, (cost, _, fn) in SCENARIOS.items():
            print(f"  {name:24s} {cost:9s} {(fn.__doc__ or '').splitlines()[0]}")
        return 0

    chosen = args.scenarios or list(SCENARIOS)
    if args.free_only:
        chosen = [n for n in chosen if SCENARIOS[n][0] == "free"]

    unknown = [n for n in chosen if n not in SCENARIOS]
    if unknown:
        print(f"unknown scenario(s): {unknown}", file=sys.stderr)
        return 1

    pin = json.loads((ROOT / "spec" / "mcp-tools.json").read_text())
    server = (pin.get("initialize", {}).get("serverInfo") or {})
    server_label = f"{server.get('name', '')} {server.get('version', '')}".strip()

    with Recorder(budget=args.budget, spec_pin=SPEC_PIN, server=server_label) as r:
        for name in chosen:
            print(f"\n== {name} ({SCENARIOS[name][0]}) ==")
            try:
                SCENARIOS[name][2](r)
            except BudgetExceeded as exc:
                print(f"\nSTOPPED: {exc}", file=sys.stderr)
                return 2
        print(f"\noperations spent this session: {r.spent} of {args.budget}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
