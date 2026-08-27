"""The MCP surface. Band S1 says MCP, and agents are who this serves.

Everything here is a thin wrapper over `QuotaAwareAgent`, which is already
tested. No planning logic lives in this file -- if it did, the MCP path and the
library path could disagree about what fits inside an allowance, and only one
of them would be tested.

The tools mirror how an agent actually works:

    check_allowance    -- what have I got? (free; the one authoritative read)
    plan_work          -- what fits inside it? (free; spends nothing, decides nothing)
    run_work           -- do the part that fits, and tell me what you left out.
    resolve_operation  -- a person's answer about a call that was started and never
                          confirmed. Free. Without it that step could never run again,
                          which is a state the surface could enter and not leave.

`plan_work` exists as a separate tool on purpose. An agent that must commit to
work before it can find out what fits is the exact failure this build is about,
so the plan is readable without spending anything.
"""

from __future__ import annotations

import json
import os

from .agent import QuotaAwareAgent, Step
from .budget import estimate
from .client import HttpTransport, SuperDocsClient
from .idempotency import OperationLedger, State, operation_key
from .policy import Policy, WhenItDoesNotFit

SERVER_NAME = "quota-aware-agent"

#: Where the operation ledger is kept between runs. It has to outlive the
#: process, because the failure it prevents -- paying twice for the same edit --
#: is caused by a process that died. Overridable so two agents driving different
#: accounts do not share one.
LEDGER_PATH = os.environ.get(
    "QUOTA_AWARE_AGENT_LEDGER",
    os.path.expanduser("~/.quota-aware-agent/operations.jsonl"),
)


def _ledger() -> OperationLedger:
    return OperationLedger(LEDGER_PATH)


def _client() -> SuperDocsClient:
    """Own key if there is one, the shared relay if there is not.

    The precedence and the message both live in `client.resolve`, so the two
    surfaces that can hit this — here and the CLI — cannot tell an agent two
    different stories about how to fix it. The message names both routes,
    because the relay one needs no signup at all and an agent that only ever
    hears "get a key" will go and get a key it did not need.
    """
    return SuperDocsClient(HttpTransport.from_env())


def _steps(raw: list[dict]) -> list[Step]:
    out = []
    for i, s in enumerate(raw, 1):
        out.append(Step(
            step_id=str(s.get("id") or f"step-{i}"),
            instruction=str(s["instruction"]),
            sections=int(s.get("sections", 1)),
            severity=str(s.get("severity", "medium")),
        ))
    return out


def _when_it_does_not_fit(value: str) -> WhenItDoesNotFit:
    try:
        return WhenItDoesNotFit(str(value).lower())
    except ValueError:
        raise ValueError(
            f"{value!r} is not a way to handle work that does not fit. Use "
            "'degrade' to do the highest-severity part that fits, or 'refuse' "
            "to do none of it."
        ) from None


# -- the operations, as plain functions so they are testable without MCP --

def check_allowance() -> dict:
    agent = QuotaAwareAgent(_client(), ledger=_ledger())
    balance = agent.read_allowance()
    unresolved = agent.unresolved_operations()
    return {
        "remaining_operations": balance.ops,
        "authoritative": balance.authoritative,
        "resets_at": balance.as_of,
        "note": ("Authoritative right now. It stops being authoritative as soon as "
                 "work begins: the usage endpoints reject API keys, so the balance "
                 "is only readable as a side effect of making calls."),
        # Surfaced here rather than only inside run_work, because an agent that
        # is about to plan needs to know an earlier run left something in doubt
        # before it decides what to do, not after.
        "started_and_never_confirmed": unresolved,
        "budget": agent.budget_hint(),
    }


def plan_work(steps: list[dict], reserve: int = 1, session_id: str = "",
              when_it_does_not_fit: str = "degrade") -> dict:
    """Free. Spends nothing, changes nothing, and answers 'what fits?'.

    Given a `session_id` it also consults the operation ledger, so work an
    earlier run already paid for is named rather than priced. Without one it
    can only price, and it says so — a plan that quietly assumes a clean slate
    is the plan that disagrees with the run.
    """
    policy = Policy(reserve=reserve,
                    when_it_does_not_fit=_when_it_does_not_fit(when_it_does_not_fit))
    agent = QuotaAwareAgent(_client(), policy=policy, ledger=_ledger())
    balance = agent.read_allowance()
    parsed = _steps(steps)
    if session_id:
        to_price, already_applied, unconfirmed = agent.settled(session_id, parsed)
    else:
        to_price, already_applied, unconfirmed = parsed, [], []
    plan = agent.plan(to_price)
    by_id = {s.step_id: s for s in parsed}
    return {
        "remaining_operations": balance.ops,
        "full_request_costs": estimate([s.as_change() for s in to_price],
                                       batched=QuotaAwareAgent.BATCHED),
        "reserved": reserve,
        "will_run": [c.row_id for c in plan.publish],
        "will_defer": [c.row_id for c in plan.defer],
        "already_applied_by_an_earlier_run": already_applied,
        "started_and_never_confirmed": unconfirmed,
        "fits_completely": plan.complete,
        "explanation": plan.rationale or "The whole request fits inside the allowance.",
        "priced_against_the_ledger": bool(session_id),
        "pricing_note": (
            "Each step is its own billable request, so each one costs at least "
            "one operation — the sections only add to that."
            + ("" if session_id else
               " No session_id was given, so this price assumes none of these "
               "steps has been run before. Pass the session_id you will run "
               "against to have work an earlier run already paid for excluded.")
        ),
        "instructions": {k: v.instruction for k, v in by_id.items()},
        "policy": agent.policy.describe(),
        "budget": agent.budget_hint(),
    }


def run_work(session_id: str, filename: str, document_html: str = "",
             steps: list[dict] | None = None, reserve: int = 1,
             max_steps: int | None = None, export_format: str = "docx",
             document_base64: str = "", when_it_does_not_fit: str = "degrade") -> dict:
    agent = QuotaAwareAgent(
        _client(),
        policy=Policy(reserve=reserve, max_steps=max_steps,
                      when_it_does_not_fit=_when_it_does_not_fit(when_it_does_not_fit)),
        ledger=_ledger())
    report = agent.run(session_id, filename,
                       _document_bytes(document_html, document_base64),
                       _steps(steps or []), export_format=export_format)
    return {
        "completed": report.completed,
        "deferred": report.deferred,
        "stopped_because": report.stopped_because or None,
        "plain_language": report.plain_language(),
        "allowance_at_start": {
            "operations": report.balance_at_start.ops,
            "authoritative": report.balance_at_start.authoritative,
        } if report.balance_at_start else None,
        "allowance_at_end": {
            "operations": report.balance_at_end.ops,
            "authoritative": report.balance_at_end.authoritative,
        } if report.balance_at_end else None,
        "export_warnings": report.export_warnings,
        "already_applied_by_an_earlier_run": report.already_applied,
        "started_and_never_confirmed": report.needs_a_person,
        "stop_reason": report.stop_reason.value,
        "why_it_stopped": report.stop_reason.explain(),
        # The line items and whether they add up. An agent that has to derive
        # its own spend from a transcript will get it wrong the same way a
        # person does.
        "receipt": report.receipt.as_dict(report.balance_at_start,
                                          report.balance_at_end),
        "budget": agent.budget_hint(),
    }


def resolve_operation(session_id: str, step_id: str, instruction: str,
                      sections: int, applied: bool, note: str = "") -> dict:
    """Close out a step an earlier run started and never confirmed.

    Without this the surface has a state it can enter and never leave: a call
    recorded as started-and-unconfirmed is never retried, which is correct, and
    was never resolvable through the surface, which is not — the step could
    never run again. Somebody has to open the document, see whether the edit is
    there, and say so. This is where they say it.

    It is deliberately not automatic. Choosing between paying twice and leaving
    work undone is somebody's money and somebody's document.
    """
    ledger = _ledger()
    key = operation_key(session_id, step_id, instruction, int(sections))
    before = ledger.get(key)
    if before.state is not State.IN_FLIGHT:
        return {
            "resolved": False,
            "state": before.state.value,
            "explanation": (
                f"'{step_id}' is recorded as '{before.state.value}', not as "
                "started-and-unconfirmed, so there is nothing to resolve. Only "
                "a call that was sent and whose outcome was never learned needs "
                "a person. Check that the session_id, step id, instruction and "
                "section count match the run exactly — the ledger is keyed on "
                "what the call is, not on an id you assigned."
            ),
        }
    after = ledger.resolve(key, applied=applied, note=note)
    return {
        "resolved": True,
        "state": after.state.value,
        "explanation": (
            f"'{step_id}' is now recorded as already applied; a later run will "
            "not repeat it and will not be billed for it again."
            if applied else
            f"'{step_id}' is now recorded as never applied; a later run will "
            "send it. Only say this if you looked at the document and the edit "
            "is not there."
        ),
    }


def _document_bytes(document_html: str, document_base64: str) -> bytes:
    """The document to upload, from whichever form the caller had it in.

    HTML is the convenient case and base64 is the necessary one: an agent
    holding a real .docx has no lossless way to put it through a JSON string
    field, and SuperDocs takes documents, not raw Word XML. Offering only the
    HTML field quietly restricted this build to callers who had already
    converted their file — which is most of the work.
    """
    import base64 as _b64
    import binascii

    if document_base64:
        if document_html:
            raise ValueError(
                "give document_html or document_base64, not both — one of them "
                "would be silently ignored and you would not know which.")
        try:
            return _b64.b64decode(document_base64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError(
                f"document_base64 is not valid base64 ({e}). Send the file's "
                "bytes base64-encoded, not its text.") from None
    if not document_html:
        raise ValueError(
            "no document was given. Pass document_html for HTML, or "
            "document_base64 for the bytes of a .docx or .pdf.")
    return document_html.encode("utf-8")


TOOLS = [
    {
        "name": "check_allowance",
        "description": (
            "Read how many SuperDocs operations remain before planning any work. "
            "Free. This is the one moment the number is authoritative -- afterwards "
            "it can only be inferred from the responses to work you have already done."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "plan_work",
        "description": (
            "Price a list of edits against the remaining allowance and report what "
            "fits, what would be deferred, and why -- WITHOUT doing any of it. Free. "
            "Call this before run_work so you never start a job you cannot finish."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": "The edits you want to make.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "instruction": {"type": "string",
                                            "description": "A natural-language edit instruction."},
                            "sections": {"type": "integer", "minimum": 1,
                                         "description": "Roughly how many document sections it "
                                                        "touches. SuperDocs bills one operation "
                                                        "per 25 sections edited."},
                            "severity": {"type": "string",
                                         "enum": ["critical", "high", "medium", "low"],
                                         "description": "Highest severity runs first when not "
                                                        "everything fits."},
                        },
                        "required": ["instruction"],
                    },
                },
                "reserve": {"type": "integer", "minimum": 0, "default": 1,
                            "description": "Operations held back so finished work can still "
                                           "be exported."},
                "session_id": {"type": "string",
                               "description": "The session you will run against. Given one, "
                                              "steps an earlier run already paid for are "
                                              "excluded from the price instead of quoted."},
                "when_it_does_not_fit": {
                    "type": "string", "enum": ["degrade", "refuse"], "default": "degrade",
                    "description": "degrade: do the highest-severity part that fits. "
                                   "refuse: do none of it rather than deliver a subset."},
            },
            "required": ["steps"],
        },
    },
    {
        "name": "run_work",
        "description": (
            "Upload a document, apply the edits that fit inside the remaining "
            "allowance, approve the proposed changes, and export the result. "
            "Degrades rather than failing halfway: it never starts a step it cannot "
            "finish, and it reports in plain language what it left out."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "filename": {"type": "string"},
                "document_html": {"type": "string",
                                  "description": "The document as HTML. SuperDocs takes "
                                                 "documents and HTML, never raw Word XML. "
                                                 "Use document_base64 instead for a real file."},
                "document_base64": {"type": "string",
                                    "description": "The document's bytes, base64-encoded — for "
                                                   "a .docx or .pdf you already hold. Give this "
                                                   "or document_html, never both."},
                "steps": {"type": "array", "items": {"type": "object"}},
                "reserve": {"type": "integer", "default": 1},
                "max_steps": {"type": ["integer", "null"],
                              "description": "Small-sample bound: run at most this many steps."},
                "export_format": {"type": "string",
                                  "enum": ["docx", "pdf", "html", "markdown", "txt"],
                                  "default": "docx"},
                "when_it_does_not_fit": {
                    "type": "string", "enum": ["degrade", "refuse"], "default": "degrade",
                    "description": "degrade: do the highest-severity part that fits and name "
                                   "the rest. refuse: start nothing rather than deliver a "
                                   "subset."},
            },
            "required": ["session_id", "filename", "steps"],
        },
    },
    {
        "name": "resolve_operation",
        "description": (
            "Close out a step that check_allowance or run_work reported as "
            "'started and never confirmed'. Such a step is never retried automatically, "
            "because retrying might be charged twice and might apply the same edit twice — "
            "so a person opens the document, sees whether the edit is there, and records "
            "the answer here. Free. Until it is resolved, that step will not run again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "step_id": {"type": "string"},
                "instruction": {"type": "string",
                                "description": "The instruction exactly as it was sent. The "
                                               "ledger is keyed on what the call is, not on "
                                               "an id you assigned."},
                "sections": {"type": "integer", "minimum": 1,
                             "description": "The section count exactly as it was sent."},
                "applied": {"type": "boolean",
                            "description": "true if the edit IS in the document — it will not "
                                           "be sent or billed again. false if it is NOT — it "
                                           "will be sent on the next run."},
                "note": {"type": "string", "description": "What you saw, for the record."},
            },
            "required": ["session_id", "step_id", "instruction", "sections", "applied"],
        },
    },
]

_HANDLERS = {
    "check_allowance": lambda a: check_allowance(),
    "plan_work": lambda a: plan_work(
        a["steps"], a.get("reserve", 1), a.get("session_id", ""),
        a.get("when_it_does_not_fit", "degrade"),
    ),
    "run_work": lambda a: run_work(
        a["session_id"], a["filename"], a.get("document_html", ""), a["steps"],
        a.get("reserve", 1), a.get("max_steps"), a.get("export_format", "docx"),
        a.get("document_base64", ""), a.get("when_it_does_not_fit", "degrade"),
    ),
    "resolve_operation": lambda a: resolve_operation(
        a["session_id"], a["step_id"], a["instruction"], a["sections"],
        bool(a["applied"]), a.get("note", ""),
    ),
}


def dispatch(name: str, arguments: dict) -> dict:
    """The whole surface, callable without an MCP client -- which is what makes
    it testable offline."""
    if name not in _HANDLERS:
        raise KeyError(f"no tool named {name!r}")
    return _HANDLERS[name](arguments or {})


async def serve() -> None:
    """Serve the three tools over stdio.

    Written against the MCP SDK's constructor-callback API (2.x). The older
    `@server.list_tools()` decorators do not exist there, and a server that
    imports cleanly but cannot start is worse than one that fails loudly, so
    `test_the_server_starts_and_advertises_its_tools` drives a real client.
    """
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    def _tool(spec: dict) -> "types.Tool":
        return types.Tool(
            name=spec["name"],
            description=spec["description"],
            input_schema=spec["inputSchema"],
        )

    async def on_list_tools(ctx, params) -> "types.ListToolsResult":
        return types.ListToolsResult(tools=[_tool(t) for t in TOOLS])

    async def on_call_tool(ctx, params) -> "types.CallToolResult":
        try:
            result = dispatch(params.name, params.arguments or {})
            failed = False
        except Exception as e:
            # An agent must be able to READ the failure. Letting it propagate
            # drops the connection and tells the caller nothing actionable.
            result, failed = {"error": str(e)}, True
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, indent=2))],
            is_error=failed,
        )

    server = Server(
        SERVER_NAME,
        version="1.0.0",
        instructions=(
            "Call check_allowance first, then plan_work to see what fits, then "
            "run_work. Everything except run_work is free and changes nothing. "
            "If check_allowance reports work started and never confirmed, a "
            "person has to look at the document and answer with "
            "resolve_operation before that step can run again."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    import asyncio

    asyncio.run(serve())


if __name__ == "__main__":
    main()
