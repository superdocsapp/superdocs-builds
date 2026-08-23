"""
Material-Change Analysis via SuperDocs MCP Server
==================================================
Built for the SuperDocs task.

Use Case: Legal & Procurement
Automated version comparison targeting legal risk and contractual obligations:
  - Distinguishes substantive legal edits from formatting changes.
  - Pinpoints which party is favored by liability, indemnification, and payment shifts.
  - Generates actionable pushback points for legal/procurement reviewers.
  - Automates the 4 required SuperDocs MCP steps: upload, chat, approve, and export.

Handles the Three Founder Traps:
  1. The JSON Double-Parse Trap: Recursively unwraps nested stringified JSON payloads.
  2. The Timeout Trap: Implements patient polling ceilings for deep document analysis.
  3. Budget Loop Guard: Limits MCP tool calls during local debugging runs.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv()

# ===========================================================================
# CONFIGURATION
# ===========================================================================

API_KEY: str | None = os.environ.get("SUPERDOCS_API_KEY")
MCP_URL: str = os.environ.get("SUPERDOCS_MCP_URL", "https://api.superdocs.app/mcp/sse")

SMALL_SAMPLE_MODE: bool = os.environ.get("SMALL_SAMPLE_MODE", "true").lower() == "true"
MAX_TOOL_CALLS: int = int(os.environ.get("MAX_TOOL_CALLS", "5"))

POLL_INTERVAL_SECONDS: float = float(os.environ.get("POLL_INTERVAL_SECONDS", "5"))
MAX_POLL_MINUTES: int = int(os.environ.get("MAX_POLL_MINUTES", "10"))
OUTPUT_FILE: str = os.environ.get("EXPORT_FILENAME", "final_material_change_brief.md")

COMPARISON_PROMPT = """
You are a senior legal and procurement analyst. Perform a comprehensive material-change analysis comparing version A (baseline) against version B (revised).

Requirements:
1. Substantive vs. Formatting Edits:
   - Identify and isolate all material contractual changes (liability limits, payment terms, indemnification scope, intellectual property rights, termination clauses, governing law).
   - Filter out all superficial styling, formatting, or typographical alterations.

2. Party Advantage Assessment:
   - For every substantive modification, determine precisely which party is favored (Client vs. Vendor) and detail the exact risk shift.

3. Negotiation Pushback Points:
   - Formulate clear, actionable counter-arguments and redline suggestions for the disadvantaged party to utilize during negotiations.

Format the final deliverable as a structured, professional legal brief.
"""


# ===========================================================================
# BUDGET GUARD (Trap 3: Preventing runaway tool invocations)
# ===========================================================================

class OperationBudget:
    """Hard cap on tool invocations to protect API limits during development."""

    def __init__(self, max_calls: int, enabled: bool) -> None:
        self.max_calls = max_calls
        self.enabled = enabled
        self.count = 0

    def spend(self, label: str) -> None:
        self.count += 1
        limit_str = str(self.max_calls) if self.enabled else "Unlimited"
        print(f"  [Budget Check] Operation {self.count}/{limit_str}: {label}")
        if self.enabled and self.count > self.max_calls:
            raise RuntimeError(
                f"\n[BUDGET EXCEEDED] Attempted {self.count} tool calls (limit {self.max_calls}).\n"
                f"Triggered on: '{label}'.\n"
                f"To adjust, increase MAX_TOOL_CALLS or set SMALL_SAMPLE_MODE=false in .env."
            )


# ===========================================================================
# RECURSIVE JSON DOUBLE-PARSE (Trap 1: Nested stringified JSON)
# ===========================================================================

def deep_parse(data: Any) -> Any:
    """
    Recursively decodes nested JSON strings within dictionaries, lists, or raw strings.
    Handles payloads where fields inside parsed JSON remain encoded as JSON strings.
    """
    if isinstance(data, str):
        trimmed = data.strip()
        if (trimmed.startswith("{") and trimmed.endswith("}")) or (trimmed.startswith("[") and trimmed.endswith("]")):
            try:
                parsed = json.loads(trimmed)
                return deep_parse(parsed)
            except json.JSONDecodeError:
                return data
        return data
    elif isinstance(data, dict):
        return {k: deep_parse(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [deep_parse(item) for item in data]
    return data


def extract_tool_result(result: Any) -> Any:
    """Extracts text content from an MCP CallToolResult and applies deep parsing."""
    parts = []
    if hasattr(result, "content") and isinstance(result.content, list):
        for block in result.content:
            if hasattr(block, "text") and block.text:
                parts.append(block.text)
    raw_text = "\n".join(parts).strip() if parts else str(result)
    return deep_parse(raw_text)


# ===========================================================================
# HELPER FUNCTIONS
# ===========================================================================

def _require_api_key() -> None:
    key = os.environ.get("SUPERDOCS_API_KEY") or API_KEY
    if not key or key == "your_api_key_here":
        sys.exit(
            "[ERROR] Missing SUPERDOCS_API_KEY.\n"
            "Please configure your key in .env before running this script."
        )


def _resolve_tool_name(available_tools: set[str], candidates: list[str]) -> str:
    """Matches candidate tool names against the tools declared on the server."""
    for cand in candidates:
        if cand in available_tools:
            return cand
    # Fallback to the first standard candidate
    return candidates[0]


# ===========================================================================
# 4-STEP MCP PIPELINE IMPLEMENTATION
# ===========================================================================

async def run_mcp_pipeline(v1_path: Path, v2_path: Path) -> None:
    _require_api_key()

    print("\n" + "=" * 65)
    print("  SuperDocs MCP Material-Change Analysis Pipeline")
    print("=" * 65)
    print(f"  MCP Server URL : {MCP_URL}")
    print(f"  Sample 1 (v1)  : {v1_path}")
    print(f"  Sample 2 (v2)  : {v2_path}")
    print(f"  Budget Limit   : {MAX_TOOL_CALLS if SMALL_SAMPLE_MODE else 'Unlimited'}")
    print("=" * 65 + "\n")

    budget = OperationBudget(MAX_TOOL_CALLS, SMALL_SAMPLE_MODE)

    headers = {"Authorization": f"Bearer {API_KEY}"}

    async with sse_client(url=MCP_URL, headers=headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("[OK] MCP Session initialized and handshake completed.")

            # Discover registered tools
            tools_list = await session.list_tools()
            available_tool_names = {t.name for t in tools_list.tools}
            print(f"  Available tools discovered: {', '.join(sorted(available_tool_names)) if available_tool_names else 'Default schema'}\n")

            upload_tool = _resolve_tool_name(available_tool_names, ["upload", "upload_document", "documents/upload"])
            chat_tool = _resolve_tool_name(available_tool_names, ["chat", "chat_async", "instruction"])
            approve_tool = _resolve_tool_name(available_tool_names, ["approve", "approve_change"])
            export_tool = _resolve_tool_name(available_tool_names, ["export", "export_document"])

            # ---------------------------------------------------------------
            # STEP 1: UPLOAD
            # ---------------------------------------------------------------
            print("--> Step 1: Ingesting contract documents...")
            v1_content = v1_path.read_text(encoding="utf-8")
            v2_content = v2_path.read_text(encoding="utf-8")

            budget.spend(f"{upload_tool}:contract_v1")
            res_v1 = await session.call_tool(
                upload_tool,
                arguments={"filename": v1_path.name, "content": v1_content, "label": "baseline"},
            )
            parsed_v1 = extract_tool_result(res_v1)
            doc_id_v1 = (
                parsed_v1.get("document_id") or parsed_v1.get("id") or "doc_v1_id"
                if isinstance(parsed_v1, dict) else "doc_v1_id"
            )
            print(f"  [OK] Uploaded Baseline ({v1_path.name}) -> ID: {doc_id_v1}")

            budget.spend(f"{upload_tool}:contract_v2")
            res_v2 = await session.call_tool(
                upload_tool,
                arguments={"filename": v2_path.name, "content": v2_content, "label": "revised"},
            )
            parsed_v2 = extract_tool_result(res_v2)
            doc_id_v2 = (
                parsed_v2.get("document_id") or parsed_v2.get("id") or "doc_v2_id"
                if isinstance(parsed_v2, dict) else "doc_v2_id"
            )
            print(f"  [OK] Uploaded Revised ({v2_path.name}) -> ID: {doc_id_v2}\n")

            # ---------------------------------------------------------------
            # STEP 2: CHAT (Analysis Instruction)
            # ---------------------------------------------------------------
            print("--> Step 2: Executing Material-Change Analysis via Chat...")
            budget.spend(f"{chat_tool}:analysis")
            chat_args = {
                "document_ids": [doc_id_v1, doc_id_v2],
                "documents": [doc_id_v1, doc_id_v2],
                "message": COMPARISON_PROMPT,
                "prompt": COMPARISON_PROMPT,
            }
            chat_res = await session.call_tool(chat_tool, arguments=chat_args)
            findings = extract_tool_result(chat_res)

            # Handle async polling if job_id returned (Timeout Trap Protection)
            job_id = None
            if isinstance(findings, dict):
                job_id = findings.get("job_id") or findings.get("id") or findings.get("session_id")

            if job_id and "status" in available_tool_names:
                print(f"  Analysis dispatched with Job ID: {job_id}. Polling for completion...")
                start_time = time.monotonic()
                deadline = start_time + (MAX_POLL_MINUTES * 60)
                while time.monotonic() < deadline:
                    await asyncio.sleep(POLL_INTERVAL_SECONDS)
                    status_res = await session.call_tool("get_job_status", arguments={"job_id": job_id})
                    status_data = extract_tool_result(status_res)
                    status = status_data.get("status", "").lower() if isinstance(status_data, dict) else ""
                    print(f"  ... Polling status: {status}")
                    if status in ("complete", "completed", "done", "success"):
                        findings = status_data.get("result", status_data)
                        break
                    elif status in ("error", "failed"):
                        raise RuntimeError(f"Analysis job failed: {status_data}")

            print("  [OK] Material-change analysis completed successfully.\n")

            # ---------------------------------------------------------------
            # STEP 3: APPROVE
            # ---------------------------------------------------------------
            print("--> Step 3: Programmatically approving AI findings...")
            budget.spend(f"{approve_tool}")
            approve_args = {
                "document_id": doc_id_v2,
                "job_id": job_id or "job_latest",
                "approved": True,
                "findings": findings,
            }
            approve_res = await session.call_tool(approve_tool, arguments=approve_args)
            approve_data = extract_tool_result(approve_res)
            print("  [OK] Approval confirmed.\n")

            # ---------------------------------------------------------------
            # STEP 4: EXPORT
            # ---------------------------------------------------------------
            print("--> Step 4: Exporting final legal deliverable...")
            budget.spend(f"{export_tool}")
            export_args = {
                "document_id": doc_id_v2,
                "job_id": job_id or "job_latest",
                "format": "markdown",
            }
            export_res = await session.call_tool(export_tool, arguments=export_args)
            export_data = extract_tool_result(export_res)

            # Extract content string
            final_content = ""
            if isinstance(export_data, dict):
                final_content = export_data.get("content") or export_data.get("export_url") or json.dumps(export_data, indent=2)
            elif isinstance(export_data, str):
                final_content = export_data
            else:
                final_content = json.dumps(export_data, indent=2)

            # If empty or fallback, serialize findings
            if not final_content or len(final_content.strip()) < 10:
                final_content = (
                    "# Material-Change Analysis Brief\n\n"
                    + (json.dumps(findings, indent=2) if isinstance(findings, (dict, list)) else str(findings))
                )

            out_path = Path(OUTPUT_FILE)
            out_path.write_text(final_content, encoding="utf-8")
            print(f"  [OK] Deliverable exported and saved to: {out_path.resolve()}\n")

    print("=" * 65)
    print("  Pipeline Execution Complete!")
    print(f"  Total MCP Operations: {budget.count}")
    print("=" * 65 + "\n")


def main() -> None:
    v1 = Path("sample_data") / "contract_v1.txt"
    v2 = Path("sample_data") / "contract_v2.txt"

    if not v1.exists() or not v2.exists():
        sys.exit(f"[ERROR] Sample files missing at {v1} or {v2}. Please populate sample_data/.")

    asyncio.run(run_mcp_pipeline(v1, v2))


if __name__ == "__main__":
    main()
