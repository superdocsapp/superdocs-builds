"""
@file: backend/mcp/server.py
@description: FastMCP server exposing the whole digest workflow as tools, so an agent
    can drive it end to end without the web UI. Deliberately includes the approval gate:
    the same control a human uses in the browser is available as a tool, which is what
    makes the system machine-drivable rather than merely machine-observable.
@flow: an MCP client connects -> start_run schedules a run -> get_run_status polls until
    AWAITING_APPROVAL -> list_approval_items shows what needs a decision ->
    approve_run_items records decisions and resumes -> export_digest returns the path.
@dependencies:
    - fastmcp: tool registration and transport
    - backend.agents.graph: the same execution entry points the HTTP API uses
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.agents.state import STAGES, state_summary
from backend.config import settings
from backend.db.database import init_db, session_scope
from backend.models import ApprovalItem, ApprovalStatus, Run, RunStatus, Theme, utcnow

logger = logging.getLogger(__name__)

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - import guard for environments without fastmcp
    FastMCP = None  # type: ignore[assignment]

mcp = FastMCP("vocdigest") if FastMCP else None


def _require_mcp():
    if mcp is None:
        raise RuntimeError(
            "fastmcp is not installed. Install it with `pip install fastmcp` to run the "
            "MCP server."
        )
    return mcp


async def _run_in_background(run_uuid: uuid.UUID) -> None:
    try:
        await execute_run(run_uuid)
    except Exception:  # noqa: BLE001 - background boundary
        logger.exception("MCP-triggered run %s failed", run_uuid)


def _register_tools() -> None:
    """Register every tool. Split out so the import guard above stays readable."""
    server = _require_mcp()

    @server.tool()
    async def start_run(
        conversations_path: str,
        last_digest_path: str | None = None,
        quarter_label: str = "Q3 2026",
        wait: bool = False,
    ) -> dict[str, Any]:
        """Start a new Voice-of-Customer digest run.

        Args:
            conversations_path: Path to a CSV, JSON, or TXT file of support conversations.
            last_digest_path: Optional path to the prior quarter's digest for comparison.
            quarter_label: Label for the quarter being analysed.
            wait: If true, block until the run pauses or finishes instead of returning
                immediately. Useful for agents that would otherwise poll.

        Returns the run_id and status. The run will pause at AWAITING_APPROVAL until
        approve_run_items is called.
        """
        source = Path(conversations_path)
        if not source.is_file():
            return {"error": f"Conversations file not found: {conversations_path}"}
        if last_digest_path and not Path(last_digest_path).is_file():
            return {"error": f"Prior digest not found: {last_digest_path}"}

        run_uuid = await create_run(
            str(source), last_digest_path, quarter_label=quarter_label
        )

        if wait:
            result = await execute_run(run_uuid)
            return {
                "run_id": str(run_uuid),
                "status": result["status"],
                "paused": result.get("paused", False),
                "reason": result.get("reason"),
                "next_step": (
                    "Call list_approval_items then approve_run_items"
                    if result["status"] == RunStatus.AWAITING_APPROVAL.value
                    else "Call get_run_status"
                ),
            }

        asyncio.create_task(_run_in_background(run_uuid))
        return {
            "run_id": str(run_uuid),
            "status": RunStatus.PENDING.value,
            "next_step": "Poll get_run_status until status is AWAITING_APPROVAL",
        }

    @server.tool()
    async def get_run_status(run_id: str) -> dict[str, Any]:
        """Get the current stage, status, and per-stage timeline of a run."""
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            run = await session.get(Run, run_uuid)
            if run is None:
                return {"error": f"Run {run_id} not found"}
            stages = (run.checkpoint_data or {}).get("stages", {})
            pending = len(
                list(
                    (
                        await session.execute(
                            select(ApprovalItem).where(
                                ApprovalItem.run_id == run_uuid,
                                ApprovalItem.status == ApprovalStatus.PENDING,
                            )
                        )
                    ).scalars()
                )
            )
            payload = {
                "run_id": run_id,
                "status": run.status.value,
                "current_stage": run.current_stage,
                "error_message": run.error_message,
                "pending_approvals": pending,
                "export_ready": bool(
                    run.export_path and Path(run.export_path).is_file()
                ),
                "timeline": [
                    {
                        "stage": s,
                        "status": (stages.get(s) or {}).get("status", "PENDING"),
                        "attempts": (stages.get(s) or {}).get("attempts", 0),
                    }
                    for s in STAGES
                ],
                "decision_log": list(run.decision_log or [])[-10:],
            }

        state = await load_state(run_uuid)
        payload["summary"] = state_summary(state)
        return payload

    @server.tool()
    async def list_approval_items(run_id: str) -> dict[str, Any]:
        """List everything awaiting a human (or agent) decision at the approval gate.

        Each item has an id, a type (THEME, QUOTE, FINDING, UPDATE) and its content.
        QUOTE items are the ones where anonymization was uncertain and a span is marked
        [POSSIBLE-NAME] — those deserve the closest look.
        """
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            items = list(
                (
                    await session.execute(
                        select(ApprovalItem)
                        .where(ApprovalItem.run_id == run_uuid)
                        .order_by(ApprovalItem.created_at)
                    )
                ).scalars()
            )

        return {
            "run_id": run_id,
            "total": len(items),
            "pending": sum(1 for i in items if i.status == ApprovalStatus.PENDING),
            "items": [
                {
                    "id": str(i.id),
                    "type": i.item_type.value,
                    "status": i.status.value,
                    "content": i.content,
                }
                for i in items
            ],
        }

    @server.tool()
    async def approve_run_items(
        run_id: str,
        approved_ids: list[str] | None = None,
        rejected_ids: list[str] | None = None,
        resume: bool = True,
    ) -> dict[str, Any]:
        """Approve or reject items at the human gate, then resume the run.

        Rejecting an item removes only that content from the digest — the rest proceeds
        and the export still works. The run resumes from exactly where it paused; no
        earlier stage is re-run.
        """
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        approved = {uuid.UUID(i) for i in (approved_ids or [])}
        rejected = {uuid.UUID(i) for i in (rejected_ids or [])}
        overlap = approved & rejected
        if overlap:
            return {
                "error": f"Item(s) both approved and rejected: {[str(i) for i in overlap]}"
            }

        async with session_scope() as session:
            items = {
                item.id: item
                for item in (
                    await session.execute(
                        select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                    )
                ).scalars()
            }
            unknown = (approved | rejected) - set(items)
            if unknown:
                return {"error": f"Unknown item(s): {[str(i) for i in unknown]}"}

            for item_id in approved:
                items[item_id].status = ApprovalStatus.APPROVED
                items[item_id].decided_at = utcnow()
            for item_id in rejected:
                items[item_id].status = ApprovalStatus.REJECTED
                items[item_id].decided_at = utcnow()

            remaining = sum(
                1 for i in items.values() if i.status == ApprovalStatus.PENDING
            )

        resumed = False
        if remaining == 0 and resume:
            result = await execute_run(run_uuid)
            resumed = True
            return {
                "run_id": run_id,
                "approved": len(approved),
                "rejected": len(rejected),
                "pending": 0,
                "resumed": True,
                "status": result["status"],
                "export_path": result.get("state", {}).get("export_path"),
            }

        return {
            "run_id": run_id,
            "approved": len(approved),
            "rejected": len(rejected),
            "pending": remaining,
            "resumed": resumed,
            "note": (
                f"{remaining} item(s) still pending — the run stays paused until every "
                f"item has a decision."
                if remaining
                else "All items decided."
            ),
        }

    @server.tool()
    async def cancel_run(run_id: str) -> dict[str, Any]:
        """Cancel a run so it stops consuming the provider token allowance.

        Takes effect at the next stage boundary. Cannot interrupt a provider call already
        in flight, so a stage mid-request will finish that request first.
        """
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            run = await session.get(Run, run_uuid)
            if run is None:
                return {"error": f"Run {run_id} not found"}
            if run.status in (RunStatus.COMPLETE, RunStatus.FAILED, RunStatus.CANCELLED):
                return {
                    "error": f"Run is already {run.status.value}",
                    "status": run.status.value,
                }
            previous = run.status.value
            run.status = RunStatus.CANCELLED
            run.error_message = "Cancelled via MCP"
            tokens = int(
                ((run.cost_report or {}).get("totals") or {}).get("groq_tokens_used", 0)
            )

        return {
            "run_id": run_id,
            "cancelled_from": previous,
            "tokens_spent": tokens,
            "note": "Completed stages are preserved. A cancelled run is not resumable.",
        }

    @server.tool()
    async def list_active_runs() -> dict[str, Any]:
        """Runs currently consuming the provider allowance, and what each has spent.

        Every run on one API key draws from the same allowance, so a forgotten run can
        exhaust it and make an unrelated new run appear broken. Check this before starting
        work, and cancel anything unwanted.
        """
        working = {
            RunStatus.PENDING, RunStatus.INGESTING, RunStatus.CLASSIFYING,
            RunStatus.EXTRACTING, RunStatus.THEMING, RunStatus.ANONYMIZING,
            RunStatus.COMPARING, RunStatus.DRAFTING, RunStatus.UPLOADING,
        }
        async with session_scope() as session:
            runs = list(
                (
                    await session.execute(select(Run).where(Run.status.in_(working)))
                ).scalars()
            )
            active = [
                {
                    "run_id": str(r.id),
                    "status": r.status.value,
                    "current_stage": r.current_stage,
                    "tokens_spent": int(
                        ((r.cost_report or {}).get("totals") or {}).get(
                            "groq_tokens_used", 0
                        )
                    ),
                }
                for r in runs
            ]
        return {
            "active_count": len(active),
            "total_tokens_spent_by_active_runs": sum(a["tokens_spent"] for a in active),
            "runs": active,
        }

    @server.tool()
    async def get_cost_report(run_id: str) -> dict[str, Any]:
        """Per-stage timing, token usage, and estimated cost for a run."""
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            run = await session.get(Run, run_uuid)
            if run is None:
                return {"error": f"Run {run_id} not found"}
            report = run.cost_report or {}

        return {
            "run_id": run_id,
            "stages": list((report.get("stages") or {}).values()),
            "totals": report.get("totals", {}),
            "note": (
                "Cost is estimated from published Groq token pricing and is not a bill. "
                "superdocs_operations counts metered API operations."
            ),
        }

    @server.tool()
    async def get_themes(run_id: str) -> dict[str, Any]:
        """Themes for a run, with volumes, trends, quotes, and evidence citations."""
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            themes = list(
                (
                    await session.execute(
                        select(Theme)
                        .where(Theme.run_id == run_uuid)
                        .order_by(Theme.volume_count.desc())
                    )
                ).scalars()
            )

        return {
            "run_id": run_id,
            "themes": [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "description": t.description,
                    "volume": t.volume_count,
                    "trend": t.volume_trend.value,
                    "growth_rate": t.growth_rate,
                    "prior_quarter_count": t.prior_quarter_count,
                    "evidence_count": len(t.evidence_refs or []),
                    "citations": [r.get("citation") for r in (t.evidence_refs or [])[:5]],
                    "quotes": [
                        {
                            "text": q.get("anonymized"),
                            "needs_review": q.get("needs_review"),
                        }
                        for q in (t.representative_quotes or [])
                    ],
                    "confidence_note": t.confidence_note,
                }
                for t in themes
            ],
        }

    @server.tool()
    async def export_digest(run_id: str) -> dict[str, Any]:
        """Return the path to the finished digest document.

        Only available once the run reaches COMPLETE. Rejected items are simply absent
        from the export — a rejection never blocks it.
        """
        try:
            run_uuid = uuid.UUID(run_id)
        except ValueError:
            return {"error": f"Invalid run_id: {run_id}"}

        async with session_scope() as session:
            run = await session.get(Run, run_uuid)
            if run is None:
                return {"error": f"Run {run_id} not found"}
            status, export_path = run.status, run.export_path

        if not export_path or not Path(export_path).is_file():
            return {
                "error": "No export available yet",
                "status": status.value,
                "hint": (
                    "Resolve the approval gate with approve_run_items, then wait for "
                    "status COMPLETE."
                ),
            }
        path = Path(export_path)
        return {
            "run_id": run_id,
            "export_path": str(path.resolve()),
            "filename": path.name,
            "size_bytes": path.stat().st_size,
            "status": status.value,
        }


if mcp is not None:
    _register_tools()


def main() -> None:
    """Entry point: `python -m backend.mcp.server`."""
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    server = _require_mcp()
    asyncio.run(init_db(create_all=False))
    logger.info("VocDigest MCP server listening on port %s", settings.mcp_port)
    server.run(transport="http", host="0.0.0.0", port=settings.mcp_port)


if __name__ == "__main__":
    main()