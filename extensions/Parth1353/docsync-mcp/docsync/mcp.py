"""An MCP server over stdio, hand-rolled against the specification.

No SDK dependency on purpose. The protocol surface a tools-only server needs is
four methods and a newline-delimited JSON framing, and writing it out means the
whole thing installs with two dependencies and can be tested by driving a real
subprocess rather than by trusting a library's own tests.

Implemented against the 2025-06-18 specification, and the details that bite are
handled explicitly:

* **stdout carries MCP messages and nothing else.** A stray ``print`` in a
  library breaks the transport in a way that looks like the server hanging.
  Every diagnostic goes to stderr, and this module never prints.
* **Messages must not contain embedded newlines.** ``json.dumps`` escapes
  newlines inside strings, which is what makes it safe to return a multi-line
  plan as one message — but only if nobody adds ``indent=``.
* **A notification gets no reply.** A message with no ``id`` — chiefly
  ``notifications/initialized`` — must produce silence, not a response with a
  null id.
* **Version negotiation is real.** If the client asks for a version we know, we
  echo it back; otherwise we answer with ours and let the client decide whether
  to continue.

## Where the human gate lives

``docsync_apply`` sends the edits and stops. It returns the proposed changes
with their ids and applies **nothing**. A second call, ``docsync_approve``, is
required, and it takes an explicit list of change ids — there is deliberately
no "approve everything" argument.

Be clear about what that does and does not buy you. It guarantees the diffs
exist and were surfaced before anything was applied, and it makes bulk approval
something a caller has to spell out change by change. It does **not** guarantee
a human read them: an agent holding both tools can call the second one itself.
Editor hosts are asked to prompt via ``destructiveHint``, and that is a request,
not a control.

If you need the gate to be enforced rather than encouraged, set
``DOCSYNC_APPROVE_MODE=cli``. ``docsync_approve`` then refuses, and the only way
to apply a staged batch is a person running ``docsync approve`` in a terminal.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Callable
from typing import Any, TextIO

from docsync.apply import commit, stage
from docsync.facts import SourceError
from docsync.registry import RegistryError
from docsync.report import (
    render_audit,
    render_facts,
    render_pending,
    render_plan,
    render_report,
)
from docsync.state import Pending, StateError
from docsync.superdocs import SuperDocsError
from docsync.workspace import Workspace

log = logging.getLogger(__name__)

SERVER_NAME = "docsync"
SERVER_VERSION = "0.1.0"
DEFAULT_PROTOCOL = "2025-06-18"
KNOWN_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

INSTRUCTIONS = """\
docsync keeps engineering documents in step with the code they describe.

Call docsync_plan first — it is free, makes no network call, and tells you
exactly which documents carry the thing that changed and what an apply would
cost. Only docsync_apply spends operations.

docsync_apply never applies anything. It sends the edits, stops at the human
gate and returns the proposed changes. Show those changes to the user and let
them decide. Do not call docsync_approve with ids the user has not seen.
"""


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------


def _baseline_props() -> dict[str, Any]:
    return {
        "base": {
            "type": "string",
            "description": "Compare against this git revision (e.g. 'main', 'HEAD~1'). "
            "Omit to compare against the snapshot recorded by the last apply.",
        },
        "base_dir": {
            "type": "string",
            "description": "Compare against another checkout on disk instead of a revision.",
        },
        "allow_prose": {
            "type": "boolean",
            "description": "Also edit documents where the old value does not appear "
            "literally. These edits cannot be verified afterwards.",
        },
    }


READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "docsync_facts",
        "title": "Read the tracked facts",
        "description": "Every value docsync tracks, extracted from the working tree right "
        "now. Free, offline, no API key needed.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "Read the tracked facts", **READ_ONLY},
    },
    {
        "name": "docsync_audit",
        "title": "Audit coverage claims",
        "description": "For each document, check that the facts it claims to carry actually "
        "appear in its text. Reports weak anchors and coverage claims that would silently "
        "do nothing. Free and offline.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "Audit coverage claims", **READ_ONLY},
    },
    {
        "name": "docsync_plan",
        "title": "Plan the documentation changes",
        "description": "Which tracked facts have moved, which documents carry them, which "
        "documents are deliberately left alone, and what applying it would cost in billable "
        "operations. Free, offline, spends nothing. Call this before docsync_apply.",
        "inputSchema": {"type": "object", "properties": _baseline_props()},
        "annotations": {"title": "Plan the documentation changes", **READ_ONLY},
    },
    {
        "name": "docsync_apply",
        "title": "Send the edits and stop for review",
        "description": "Sends one targeted edit per affected document and STOPS at the human "
        "gate. Applies nothing. Returns the proposed changes with their ids so a person can "
        "read them. Spends one operation per document edited, plus one per document that "
        "needs uploading. Show the returned diffs to the user before calling docsync_approve.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_baseline_props(),
                "max_operations": {
                    "type": "integer",
                    "description": "Hard stopping rule for this call.",
                },
                "model_tier": {
                    "type": "string",
                    "enum": ["core", "turbo", "pro", "max"],
                    "description": "Defaults to pro; these are documents where a wrong word "
                    "costs a re-review.",
                },
            },
        },
        "annotations": {
            "title": "Send the edits and stop for review",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "docsync_pending",
        "title": "Show the staged changes",
        "description": "The proposed changes waiting for a decision, with their ids. Free.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"title": "Show the staged changes", **READ_ONLY},
    },
    {
        "name": "docsync_approve",
        "title": "Apply the changes a person approved",
        "description": "Applies exactly the change ids given and rejects every other staged "
        "change. There is no approve-everything argument by design. Verifies what landed and "
        "writes the updated documents back to the working tree. Only call this with ids the "
        "user has seen and agreed to.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "change_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "The change ids to apply. Anything staged and not listed "
                    "here is rejected.",
                },
                "write_back": {
                    "type": "boolean",
                    "description": "Write the edited documents back to disk. Default true. "
                    "A file with uncommitted changes is never overwritten.",
                },
            },
            "required": ["change_ids"],
        },
        "annotations": {
            "title": "Apply the changes a person approved",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    },
    {
        "name": "docsync_discard",
        "title": "Discard the staged changes",
        "description": "Rejects every staged change and clears the batch. Nothing is applied "
        "and no document is written.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {
            "title": "Discard the staged changes",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    },
    {
        "name": "docsync_snapshot",
        "title": "Record the current values as the baseline",
        "description": "Records what the code says right now, so future plans compare against "
        "it. Free and offline. Use it when the documents are already correct.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {
            "title": "Record the current values as the baseline",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]


# ---------------------------------------------------------------------------


class ToolError(RuntimeError):
    """A tool could not do its job. Reported as isError, not as a protocol error."""


class Server:
    def __init__(self, registry_path: str = ".", max_operations: int = 40) -> None:
        self.registry_path = registry_path
        self.max_operations = max_operations
        self.initialized = False
        self.protocol = DEFAULT_PROTOCOL

    # -- transport ---------------------------------------------------------

    def run(self, stdin: TextIO, stdout: TextIO) -> int:
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is None:
                continue
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
        return 0

    def handle_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return _error(None, PARSE_ERROR, f"invalid JSON: {exc}")
        if isinstance(message, list):
            # Batching was removed in the 2025-06-18 revision, and supporting it
            # halfway is worse than saying so.
            return _error(None, INVALID_REQUEST, "JSON-RPC batches are not supported")
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return _error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 message")
        return self.handle(message)

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        # A notification has no id at all. Responding to one — even with a null
        # id — is a protocol violation that some clients treat as a fatal error.
        is_notification = "id" not in message
        request_id = message.get("id")

        if not isinstance(method, str):
            return None if is_notification else _error(request_id, INVALID_REQUEST, "no method")

        if method == "notifications/initialized":
            self.initialized = True
            return None
        if method.startswith("notifications/"):
            return None
        if is_notification:
            return None

        try:
            if method == "initialize":
                return _result(request_id, self._initialize(message.get("params") or {}))
            if method == "ping":
                return _result(request_id, {})
            if method == "tools/list":
                return _result(request_id, {"tools": TOOLS})
            if method == "tools/call":
                return self._tools_call(request_id, message.get("params") or {})
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("unhandled error in %s", method)
            return _error(request_id, INTERNAL_ERROR, str(exc))

        return _error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        asked = params.get("protocolVersion")
        self.protocol = asked if asked in KNOWN_PROTOCOLS else DEFAULT_PROTOCOL
        return {
            "protocolVersion": self.protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "docsync", "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        }

    def _tools_call(self, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _error(request_id, INVALID_PARAMS, "tools/call needs a tool name")
        handler = HANDLERS.get(name)
        if handler is None:
            return _error(request_id, METHOD_NOT_FOUND, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return _error(request_id, INVALID_PARAMS, "arguments must be an object")

        missing = [
            key
            for key in _schema_for(name).get("required", [])
            if key not in arguments
        ]
        if missing:
            return _error(
                request_id, INVALID_PARAMS, f"missing required argument(s): {', '.join(missing)}"
            )

        try:
            text = handler(self, arguments)
        except (
            ToolError,
            RegistryError,
            SourceError,
            StateError,
            SuperDocsError,
            OSError,
        ) as exc:
            # A tool that fails for an ordinary reason is a *result*, not a
            # protocol error — the model is supposed to read it and adapt.
            return _result(
                request_id,
                {"content": [{"type": "text", "text": str(exc)}], "isError": True},
            )
        return _result(request_id, {"content": [{"type": "text", "text": text}], "isError": False})

    # -- tools -------------------------------------------------------------

    def workspace(self) -> Workspace:
        """Re-opened on every call, never cached.

        The point of this tool is that the files keep changing underneath it.
        A workspace held across calls would answer questions about the repo as
        it was when the editor started.
        """
        return Workspace.open(self.registry_path)


def _tool_facts(server: Server, _args: dict) -> str:
    return render_facts(server.workspace().facts_now())


def _tool_audit(server: Server, _args: dict) -> str:
    return render_audit(server.workspace().audit())


def _tool_plan(server: Server, args: dict) -> str:
    workspace = server.workspace()
    plan = workspace.plan(
        base=str(args.get("base") or ""),
        base_dir=str(args.get("base_dir") or ""),
        allow_prose=bool(args.get("allow_prose")),
    )
    return render_plan(plan)


def _tool_apply(server: Server, args: dict) -> str:
    workspace = server.workspace()
    plan = workspace.plan(
        base=str(args.get("base") or ""),
        base_dir=str(args.get("base_dir") or ""),
        allow_prose=bool(args.get("allow_prose")),
    )
    if plan.blocked:
        raise ToolError(
            "Refusing to send anything: "
            + "; ".join(f"{k}: {v.splitlines()[0]}" for k, v in plan.unresolved.items())
            + "\n\nA fact that cannot be read has no new value, and writing a guess into a "
            "document is the failure this tool exists to prevent."
        )
    if not any(doc.to_send for doc in plan.documents):
        return render_plan(plan)

    existing = Pending.load(workspace.root)
    if existing and existing.jobs:
        raise ToolError(
            f"{existing.change_count} change(s) are already staged and waiting for a "
            f"decision. Call docsync_approve or docsync_discard first — staging a second "
            f"batch on top would lose the first one's ids."
        )

    limit = args.get("max_operations")
    budget = int(limit) if isinstance(limit, int) else server.max_operations
    if plan.operations > budget:
        raise ToolError(
            f"the plan needs {plan.operations} operations and the budget is {budget}. "
            f"Raise max_operations or narrow the change."
        )

    with workspace.client(max_operations=budget) as client:
        pending = stage(
            client,
            plan,
            workspace.state,
            session_prefix=workspace.session_id,
            model_tier=str(args.get("model_tier") or "pro"),
        )
        cost = client.ledger.summary()

    more = (
        f"\n\nThis change needs {plan.rounds} rounds in total — one changed fact per "
        f"document per round. After approving this batch, call docsync_apply again for "
        f"the next one."
        if plan.rounds > 1
        else ""
    )
    return (
        render_plan(plan)
        + "\n\n=== STAGED — nothing has been applied ===\n\n"
        + render_pending(pending)
        + "\n\nShow these to the user. Call docsync_approve with the ids they agree to; "
        "everything not listed is rejected. docsync_discard rejects all of them."
        + more
        + f"\n\ncost so far: {json.dumps(cost)}"
    )


def _tool_pending(server: Server, _args: dict) -> str:
    pending = Pending.load(server.workspace().root)
    return render_pending(pending) if pending else "Nothing is staged."


def _tool_approve(server: Server, args: dict) -> str:
    if os.environ.get("DOCSYNC_APPROVE_MODE", "tool").lower() == "cli":
        raise ToolError(
            "approval is restricted to the command line in this workspace "
            "(DOCSYNC_APPROVE_MODE=cli). Ask the user to run `docsync approve` in a "
            "terminal, where they will be shown each change and asked."
        )
    workspace = server.workspace()
    pending = Pending.load(workspace.root)
    if pending is None or not pending.jobs:
        raise ToolError("nothing is staged; call docsync_apply first")

    raw_ids = args.get("change_ids")
    if not isinstance(raw_ids, list) or not all(isinstance(i, str) for i in raw_ids):
        raise ToolError("change_ids must be a list of strings")
    wanted = set(raw_ids)

    staged = {c.change_id for job in pending.jobs for c in job.changes}
    unknown = sorted(wanted - staged)
    if unknown:
        raise ToolError(
            f"these ids are not in the staged batch: {', '.join(unknown)}\n"
            f"staged ids are: {', '.join(sorted(staged)) or 'none'}"
        )

    decisions = {change_id: change_id in wanted for change_id in staged}
    with workspace.client(max_operations=server.max_operations) as client:
        report = commit(
            client,
            pending,
            workspace.state,
            decisions=decisions,
            write_back=args.get("write_back", True) is not False,
        )
    pending.clear()
    if report.ok:
        workspace.advance_baseline()
    return (
        render_report(report)
        + (
            "\n\nBaseline updated. The documents and the code agree again."
            if report.ok
            else "\n\nBaseline NOT updated, because something did not land. The report above "
            "names it. Read the affected documents before committing."
        )
    )


def _tool_discard(server: Server, _args: dict) -> str:
    workspace = server.workspace()
    pending = Pending.load(workspace.root)
    if pending is None or not pending.jobs:
        return "Nothing was staged."
    count = pending.change_count
    with workspace.client(max_operations=server.max_operations) as client:
        commit(
            client,
            pending,
            workspace.state,
            decisions={},  # every staged change is rejected
            write_back=False,
        )
    pending.clear()
    return f"Rejected and discarded {count} staged change(s). No document was modified."


def _tool_snapshot(server: Server, _args: dict) -> str:
    workspace = server.workspace()
    count = workspace.snapshot()
    return f"Recorded {count} fact value(s) as the baseline in {workspace.state.path}."


HANDLERS: dict[str, Callable[[Server, dict], str]] = {
    "docsync_facts": _tool_facts,
    "docsync_audit": _tool_audit,
    "docsync_plan": _tool_plan,
    "docsync_apply": _tool_apply,
    "docsync_pending": _tool_pending,
    "docsync_approve": _tool_approve,
    "docsync_discard": _tool_discard,
    "docsync_snapshot": _tool_snapshot,
}


def _schema_for(name: str) -> dict[str, Any]:
    for tool in TOOLS:
        if tool["name"] == name:
            return tool["inputSchema"]
    return {}


# ---------------------------------------------------------------------------


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve(*, registry_path: str = ".", max_operations: int = 40) -> int:
    server = Server(registry_path=registry_path, max_operations=max_operations)
    log.info("docsync MCP server ready (registry=%s)", registry_path)
    return server.run(sys.stdin, sys.stdout)
