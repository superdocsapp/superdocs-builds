"""Deliberate, documented defects -- to prove the contract suite has teeth.

A suite that passes tells you nothing on its own. It might be asserting real invariants, or
it might be asserting that `200 == 200`, and from the outside those look identical. The
only way to tell them apart is to break the thing under test on purpose and check that the
suite notices.

So each mutant below violates exactly one documented behaviour, names the ledger row it
breaks, and is activated by `SDMOCK_MUTANT=M1`. `scripts/run_kill_matrix.py` boots the mock
under each one in turn, runs the suite, and records which test caught it. A mutant that
survives is not a curiosity -- it is a hole in the suite, and the fix is a new assertion,
not a smaller mutant.

Everything here is opt-in and off by default. An unset `SDMOCK_MUTANT` leaves the mock
exactly as faithful as it was.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable

MUTANT_ENV = "SDMOCK_MUTANT"

Body = Any
Headers = dict[str, str]


@dataclass(frozen=True)
class Mutant:
    """One deliberate defect, and the behaviour it is meant to violate."""

    id: str
    breaks: tuple[str, ...]
    summary: str
    why_it_matters: str
    transport: str = "rest"  # which suite run should catch it
    response: Callable[[str, str, int, Headers, Body], tuple[int, Headers, Body]] | None = None
    sse: Callable[[list, int], list] | None = None
    tools: Callable[[list[dict]], list[dict]] | None = None
    mcp_result: Callable[[dict], dict] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- helpers


def _is(template: str, *candidates: str) -> bool:
    return template in candidates


def _walk_sse_payload(data: str, edit: Callable[[dict], dict]) -> str:
    try:
        payload = json.loads(data)
    except ValueError:
        return data
    return json.dumps(edit(payload))


# --------------------------------------------------------------------------- mutants


def _m1(method, template, status, headers, body):
    """Return proposed_change_batch content already parsed."""
    return status, headers, body


def _filtered(frames, last_sequence):
    """The correct behaviour, for mutants that break something other than resume."""
    if not last_sequence:
        return list(frames)
    return [f for f in frames if (f.sequence or 0) > last_sequence]


def _m1_sse(frames, last_sequence):
    frames = _filtered(frames, last_sequence)
    out = []
    for frame in frames:
        if frame.event == "proposed_change_batch":
            def edit(payload):
                if isinstance(payload.get("content"), str):
                    payload["content"] = json.loads(payload["content"])
                return payload

            frame = type(frame)(event=frame.event,
                                data=_walk_sse_payload(frame.data, edit),
                                offset_ms=frame.offset_ms, sequence=frame.sequence)
        out.append(frame)
    return out


def _m2(method, template, status, headers, body):
    """Rename metadata.pending_changes to metadata.changes."""
    if isinstance(body, dict) and isinstance(body.get("metadata"), dict):
        metadata = dict(body["metadata"])
        if "pending_changes" in metadata:
            metadata["changes"] = metadata.pop("pending_changes")
            body = {**body, "metadata": metadata}
    return status, headers, body


def _m3(method, template, status, headers, body):
    """Drop awaiting_kind from a continue pause."""
    if isinstance(body, dict) and isinstance(body.get("metadata"), dict):
        metadata = {k: v for k, v in body["metadata"].items() if k != "awaiting_kind"}
        body = {**body, "metadata": metadata}
    return status, headers, body


def _m4(method, template, status, headers, body):
    """Accept an approve body that omits top-level `approved`."""
    if _is(template, "/v1/chat/{session_id}/approve") and status == 422:
        return 200, headers, {"status": "ok", "message": "Approval processed",
                              "batch_complete": True}
    return status, headers, body


def _m5(method, template, status, headers, body):
    """Accept /approve on a continue pause instead of refusing it."""
    if _is(template, "/v1/chat/{session_id}/approve") and status == 409:
        return 200, headers, {"status": "ok", "message": "Approval processed"}
    return status, headers, body


def _m6(method, template, status, headers, body):
    """Drop Retry-After from the application 429."""
    if status == 429:
        headers = {k: v for k, v in headers.items() if k != "retry-after"}
    return status, headers, body


def _m7(method, template, status, headers, body):
    """Serve the infrastructure throttle as JSON, hiding the distinction."""
    if status == 429 and not headers.get("content-type", "").startswith("application/json"):
        headers = {**headers, "content-type": "application/json"}
        body = {"detail": "Rate exceeded"}
    return status, headers, body


def _m8(method, template, status, headers, body):
    """Flatten the structured 413 into a bare string."""
    if status == 413 and isinstance(body, dict) and isinstance(body.get("detail"), dict):
        body = {"detail": body["detail"].get("message", "Document too large")}
    return status, headers, body


def _m9(method, template, status, headers, body):
    """Say an expandable limit is a hard cap."""
    if status == 413 and isinstance(body, dict) and isinstance(body.get("detail"), dict):
        detail = {**body["detail"], "limit_expandable": False}
        body = {**body, "detail": detail}
    return status, headers, body


def _m10_sse(frames, last_sequence):
    """Emit sequences out of order."""
    frames = _filtered(frames, last_sequence)
    if len(frames) < 3:
        return frames
    reordered = list(frames)
    reordered[1], reordered[2] = reordered[2], reordered[1]
    return reordered


def _m11_sse(frames, last_sequence):
    """Ignore last_sequence and replay everything."""
    return list(frames)


def _m12(method, template, status, headers, body):
    """Return the documented-but-wrong 415 for a legacy .doc instead of the real 400."""
    if _is(template, "/v1/documents/upload") and status == 400:
        return 415, headers, {"detail": "Unsupported file type: .doc. Supported types: "
                                        ".pdf, .docx, .txt, .rtf, .md, .html, .htm"}
    return status, headers, body


def _m13_tools(tools):
    """Drop a tool from the advertised surface."""
    return [t for t in tools if t.get("name") != "continue_chat"]


def _m14_tools(tools):
    """Rename an argument inside a tool's input schema."""
    out = []
    for tool in tools:
        if tool.get("name") == "get_document_detail":
            schema = json.loads(json.dumps(tool.get("inputSchema") or {}))
            properties = schema.get("properties") or {}
            if "include_html" in properties:
                properties["includeHtml"] = properties.pop("include_html")
                schema["properties"] = properties
            tool = {**tool, "inputSchema": schema}
        out.append(tool)
    return out


def _m15(method, template, status, headers, body):
    """Return full HTML in compact mode, defeating the whole point of it."""
    if isinstance(body, dict):
        result = body.get("result")
        if isinstance(result, dict) and isinstance(result.get("document_changes"), dict):
            changes = dict(result["document_changes"])
            if changes.get("updated_html") is None:
                changes["updated_html"] = "<p>the whole document, unhelpfully</p>"
                body = {**body, "result": {**result, "document_changes": changes}}
    return status, headers, body


def _m16_mcp(result):
    """Report a tool failure as a success."""
    if result.get("isError"):
        return {**result, "isError": False}
    return result


def _m17(method, template, status, headers, body):
    """Serve the export as JSON, matching the spec but not reality."""
    if _is(template, "/v1/documents/export") and status == 200:
        headers = {**headers, "content-type": "application/json"}
        headers.pop("content-disposition", None)
        return status, headers, {"url": "https://example.invalid/export.docx"}
    return status, headers, body


def _m18(method, template, status, headers, body):
    """Return an empty document instead of refusing an export with nothing loaded."""
    if _is(template, "/v1/documents/export") and status == 404:
        return 200, {**headers, "content-type": "application/json"}, {"empty": True}
    return status, headers, body


REGISTRY: dict[str, Mutant] = {
    m.id: m for m in [
        Mutant("M1", ("B-052",),
               "proposed_change_batch.content arrives already parsed",
               "The double-parse asymmetry is the single most warned-about trap in the "
               "integration docs. A mock that smooths it over teaches the opposite of "
               "what production does.",
               sse=_m1_sse, response=_m1),
        Mutant("M2", ("B-040",),
               "metadata.pending_changes renamed to metadata.changes",
               "A review UI reads this key to know what to show; renamed, it renders "
               "an empty approval list and the user approves nothing.",
               response=_m2),
        Mutant("M3", ("B-033", "B-034"),
               "awaiting_kind omitted from a continue pause",
               "Without it the two flavours of awaiting_approval are indistinguishable "
               "and a client calls the wrong resume endpoint.",
               response=_m3),
        Mutant("M4", ("B-041",),
               "approve accepts a batch body with no top-level `approved`",
               "The documented 422 is what tells an integrator their batch shape is "
               "wrong. Accepting it silently is worse than rejecting it.",
               response=_m4),
        Mutant("M5", ("B-036",),
               "approve on a continue pause returns 200 instead of 409",
               "The 409 is the guard rail that stops a client resolving a pause the "
               "wrong way; removing it makes the two paths silently interchangeable.",
               response=_m5),
        Mutant("M6", ("B-064",),
               "Retry-After dropped from the application 429",
               "Clients are told to honour it. Without it they either hammer the "
               "service or back off arbitrarily.",
               response=_m6),
        Mutant("M7", ("B-066",),
               "the infrastructure 429 served as JSON",
               "The two 429s need opposite handling -- one means wait for a billing "
               "cycle, the other means retry in a second. Made identical, a client "
               "cannot choose.",
               response=_m7),
        Mutant("M8", ("B-073",),
               "the 413 flattened to a bare string detail",
               "The structured body is what lets an agent recover automatically "
               "instead of surfacing a dead end to a human.",
               response=_m8),
        Mutant("M9", ("B-073", "B-074"),
               "limit_expandable flipped to false",
               "It reframes a limit that support will raise on request as a hard "
               "ceiling, and a client gives up where it should ask.",
               response=_m9),
        Mutant("M10", ("B-055",),
               "SSE sequence numbers emitted out of order",
               "Ordering is what makes resume work at all; out of order, a reconnect "
               "silently drops events.",
               sse=_m10_sse),
        Mutant("M11", ("B-056",),
               "last_sequence ignored, full history replayed",
               "A resuming client re-processes every event it already handled -- "
               "duplicated inserts being the classic symptom.",
               sse=_m11_sse),
        Mutant("M12", ("B-069",),
               "legacy .doc upload returns the documented 415 rather than the real 400",
               "Encodes the documentation instead of the behaviour. A mock that "
               "matches the docs where the service does not is worse than none.",
               response=_m12),
        Mutant("M13", ("B-095",),
               "a tool dropped from the advertised MCP surface",
               "An agent plans against tools/list. A tool that vanishes turns into a "
               "capability the agent believes it lacks.",
               transport="mcp", tools=_m13_tools),
        Mutant("M14", ("B-100",),
               "a tool's input argument renamed in its schema",
               "Renamed arguments are the quietest possible break: the tool still "
               "exists, still runs, and ignores what you pass it.",
               transport="mcp", tools=_m14_tools),
        Mutant("M15", ("B-016",),
               "compact response mode returns the full document anyway",
               "Compact mode exists to keep large documents out of an agent's context. "
               "Ignoring it is a silent cost regression, not a visible failure.",
               response=_m15),
        Mutant("M16", ("B-063",),
               "an MCP tool error reported with isError false",
               "Agents branch on isError. A refusal dressed as a success is acted on.",
               transport="mcp", mcp_result=_m16_mcp),
        Mutant("M17", ("B-083",),
               "export returns JSON, as the spec wrongly declares",
               "Would make the mock agree with the specification and disagree with "
               "the service -- exactly the drift this project exists to detect.",
               response=_m17),
        Mutant("M18", ("B-111",),
               "exporting from an empty session returns an empty document",
               "The 404 is what tells an integrator they wired the four calls out of "
               "order. An empty file ships to a user instead.",
               response=_m18),
    ]
}


def active() -> Mutant | None:
    """The mutant named by SDMOCK_MUTANT, if any. Off by default."""
    name = os.environ.get(MUTANT_ENV, "").strip().upper()
    if not name:
        return None
    mutant = REGISTRY.get(name)
    if mutant is None:
        raise SystemExit(
            f"unknown mutant {name!r}. Known: {', '.join(sorted(REGISTRY))}"
        )
    return mutant
