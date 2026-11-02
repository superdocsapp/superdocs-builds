"""MCP door to the RFE response builder.

Every tool is a thin wrapper over the same core functions the CLI
(rfe.py) calls — one core, two doors, never two implementations. The
human-approval gate survives here: draft_response stops at proposed
changes, and nothing is applied until decide_changes is called with an
explicit decision.

Run: python mcp_server.py   (stdio transport; an MCP client launches it)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from mcp.server import MCPServer

from rfe import check_core, decide_core, draft_core, judge_core, preview_core

server = MCPServer(
    name="rfe-response-builder",
    instructions=(
        "Builds an immigration RFE response on SuperDocs. Typical flow: "
        "check_key → preview_case (free) → draft_response (billable, stops "
        "for review) → decide_changes (explicit approval; may loop over "
        "several rounds) → the final export is written and verified when "
        "the job completes. A case_dir holds notice/ (one file) and "
        "petition/ (the original petition documents); formats: "
        ".md .txt .pdf .docx."
    ),
)


def _case(case_dir: str) -> Path:
    return Path(case_dir) if case_dir else ROOT / "data"


@server.tool()
def check_key() -> dict:
    """Verify the SuperDocs API key from .env. Free, bills nothing."""
    return check_core()


@server.tool()
def preview_case(case_dir: str = "") -> dict:
    """Parse the officer's notice into requests and locate petition
    material for each — the offline coverage checklist. Free, no network
    call. Default case_dir: the bundled sample case in ./data."""
    return preview_core(_case(case_dir))


@server.tool()
def judge_coverage(case_dir: str = "") -> dict:
    """Have the SuperDocs model judge, per officer request, whether the
    located petition material fully, partially, or not at all answers the
    concern. A billable call, though the observed judge question charged
    0; actual charges appear in the SuperDocs Billing tab."""
    return judge_core(_case(case_dir))


@server.tool()
def draft_response(case_dir: str = "") -> dict:
    """Judge coverage, build the response skeleton, upload it with the
    petition documents attached, and ask the SuperDocs model to draft
    every response section. This is the billable step (observed: a full run
    billed 1 operation; actual charges appear in the SuperDocs Billing
    tab). STOPS at
    the human gate: returns the proposed changes for review; nothing is
    applied until decide_changes approves them. Re-running resumes the
    same job instead of paying again."""
    return draft_core(_case(case_dir))


@server.tool()
def decide_changes(
    approve_all: bool | None = None, decisions: list[dict] | None = None
) -> dict:
    """Apply an explicit review decision to the pending proposed changes.
    Pass approve_all=true/false, OR a per-change decisions list:
    [{"change_id": "...", "approved": true|false, "feedback": "optional —
    feedback makes the model re-propose that change"}]. On completion the
    final document is exported and verified; a new round of proposed
    changes stops for its own review instead."""
    return decide_core(decisions=decisions, approve_all=approve_all)


if __name__ == "__main__":
    server.run("stdio")
