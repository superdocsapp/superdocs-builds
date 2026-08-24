from typing import Any
from uuid import UUID

from mcp.server import MCPServer

from docrelay.domain.enums import ConflictChoice
from docrelay.services.machine import MachineOperations
from docrelay.services.superdocs_workflow import DecisionInput


def create_mcp_server(operations: MachineOperations) -> MCPServer:
    """Expose application services over MCP without owning workflow state or policy."""
    server = MCPServer(
        "DocRelay",
        instructions=(
            "Operate DocRelay's durable Google-to-SuperDocs workflow. Review decisions are "
            "always explicit and per run. Never treat discovery access as write authorization."
        ),
    )

    @server.tool()
    async def list_watch_roots() -> list[dict[str, Any]]:
        """List configured watched Google Drive roots and their schedules."""
        rows = await operations.watch().list_watches()
        return [_watch_payload(row) for row in rows]

    @server.tool()
    async def get_watch_root(watch_id: UUID) -> dict[str, Any]:
        """Get one watched root and its current schedule state."""
        return _watch_payload(await operations.watch().get_watch(watch_id))

    @server.tool()
    async def configure_watch_root(
        connection_id: UUID,
        root_folder_id: str,
        interval_seconds: int = 300,
        enabled: bool = False,
    ) -> dict[str, Any]:
        """Configure a selected root; this does not approve or write any document."""
        row = await operations.watch().configure_root(
            connection_id=connection_id,
            root_folder_id=root_folder_id,
            interval_seconds=interval_seconds,
            enabled=enabled,
        )
        return _watch_payload(row)

    @server.tool()
    async def set_watch_schedule(
        watch_id: UUID, enabled: bool, interval_seconds: int
    ) -> dict[str, Any]:
        """Enable, disable, or change a watched root's interval schedule."""
        row = await operations.watch().set_schedule(
            watch_id, enabled=enabled, interval_seconds=interval_seconds
        )
        return _watch_payload(row)

    @server.tool()
    async def list_watch_rules(watch_id: UUID) -> list[dict[str, Any]]:
        """List immutable rule versions configured for one watched root."""
        rows = await operations.watch().list_rules(watch_id)
        return [_rule_payload(row) for row in rows]

    @server.tool()
    async def configure_watch_rule(
        watch_id: UUID,
        folder_id: str,
        instruction: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        """Create an immutable rule version for a folder within a watched root."""
        row = await operations.watch().configure_rule(
            watch_id,
            folder_id=folder_id,
            instruction=instruction,
            enabled=enabled,
        )
        return _rule_payload(row)

    @server.tool()
    async def list_watch_scans(watch_id: UUID) -> list[dict[str, Any]]:
        """List durable scan history for one watched root."""
        rows = await operations.watch().list_scans(watch_id)
        return [_scan_payload(row) for row in rows]

    @server.tool()
    async def trigger_watch_scan(watch_id: UUID) -> dict[str, Any]:
        """Trigger or join the root's active logical scan; no review or write is inferred."""
        scan = await operations.watch().trigger_manual(watch_id)
        return (await operations.queries.get_scan(scan.id)).model_dump(mode="json")

    @server.tool()
    async def get_watch_scan(scan_id: UUID) -> dict[str, Any]:
        """Inspect a scan, every item outcome, and only the runs created by that scan."""
        return (await operations.queries.get_scan(scan_id)).model_dump(mode="json")

    @server.tool()
    async def list_scan_runs(scan_id: UUID) -> list[dict[str, Any]]:
        """List independent document runs created by one scan."""
        rows = await operations.queries.list_scan_runs(scan_id)
        return [row.model_dump(mode="json") for row in rows]

    @server.tool()
    async def list_watch_runs(watch_id: UUID) -> list[dict[str, Any]]:
        """List every durable document run linked to one watched root."""
        rows = await operations.queries.list_watch_runs(watch_id)
        return [row.model_dump(mode="json") for row in rows]

    @server.tool()
    async def get_run(run_id: UUID) -> dict[str, Any]:
        """Get detailed workflow and compact safety state for one document run."""
        run = await operations.get_run(run_id)
        summary = await operations.get_run_summary(run_id)
        return {
            "run": run.model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
        }

    @server.tool()
    async def resume_run(run_id: UUID, allow_definitive_retry: bool = False) -> dict[str, Any]:
        """Resume safe SuperDocs polling/recovery; this never supplies review decisions."""
        row = await operations.resume_run(run_id, allow_definitive_retry=allow_definitive_retry)
        return row.model_dump(mode="json")

    @server.tool()
    async def submit_review_decisions(
        run_id: UUID, decisions: list[DecisionInput]
    ) -> dict[str, Any]:
        """Explicitly approve or reject every pending proposal for exactly one run."""
        row = await operations.submit_review_decisions(run_id, tuple(decisions))
        return row.model_dump(mode="json")

    @server.tool()
    async def submit_continue(run_id: UUID, should_continue: bool) -> dict[str, Any]:
        """Explicitly answer a pending SuperDocs continue/stop review prompt."""
        row = await operations.submit_continue(run_id, should_continue=should_continue)
        return row.model_dump(mode="json")

    @server.tool()
    async def create_dry_run(run_id: UUID, proposal_id: UUID | None = None) -> dict[str, Any]:
        """Create or recover a MappingProof and WritePlan; review cannot be bypassed."""
        row = await operations.create_dry_run(run_id, proposal_id=proposal_id)
        return row.model_dump(mode="json")

    @server.tool()
    async def verify_write_authorization(run_id: UUID, file_id: str) -> dict[str, Any]:
        """Verify Picker authorization for the exact watched source file."""
        row = await operations.verify_write_authorization(run_id, picker_file_id=file_id)
        return {
            "run_id": str(run_id),
            "state": row.write_authorization_state.value,
            "checked_at": row.write_authorization_checked_at.isoformat(),
            "action": "AUTHORIZE_THIS_DOCUMENT_FOR_WRITE_BACK",
        }

    @server.tool()
    async def write_back(run_id: UUID) -> dict[str, Any]:
        """Invoke guarded per-run backup/write/verification with all existing gates."""
        row = await operations.write_back(run_id)
        return row.model_dump(mode="json")

    @server.tool()
    async def decide_write_conflict(run_id: UUID, choice: ConflictChoice) -> dict[str, Any]:
        """Explicitly cancel a conflicted run or request review against the latest source."""
        row = await operations.decide_write_conflict(run_id, choice=choice)
        return row.model_dump(mode="json")

    @server.tool()
    async def get_export(run_id: UUID) -> dict[str, Any]:
        """Verify the reviewed DOCX artifact and return metadata plus its REST download path."""
        artifact = await operations.get_export(run_id)
        return artifact.metadata.model_dump(mode="json") | {
            "download_path": f"/api/v1/runs/{run_id}/export/content"
        }

    return server


def _watch_payload(row: Any) -> dict[str, Any]:
    return {
        "watch_id": str(row.id),
        "connection_id": str(row.connection_id),
        "root_folder_id": row.parent_folder_id,
        "root_name": row.root_name,
        "enabled": row.enabled,
        "schedule": row.schedule,
        "interval_seconds": row.interval_seconds,
        "timezone": row.timezone,
        "last_scan_at": row.last_scan_at.isoformat() if row.last_scan_at else None,
        "last_successful_scan_at": (
            row.last_successful_scan_at.isoformat() if row.last_successful_scan_at else None
        ),
        "next_scan_at": row.next_scan_at.isoformat() if row.next_scan_at else None,
        "last_scan_status": row.last_scan_status.value if row.last_scan_status else None,
        "last_error_code": row.last_error_code,
    }


def _rule_payload(row: Any) -> dict[str, Any]:
    return {
        "rule_id": str(row.id),
        "watch_id": str(row.watch_config_id),
        "folder_id": row.provider_folder_id,
        "version": row.version,
        "instruction": row.instruction,
        "instruction_sha256": row.instruction_sha256,
        "enabled": row.active,
        "precedence": "nearest_enabled_ancestor",
    }


def _scan_payload(row: Any) -> dict[str, Any]:
    return {
        "scan_id": str(row.id),
        "watch_id": str(row.watch_config_id),
        "trigger": row.trigger.value,
        "status": row.status.value,
        "claim_generation": row.claim_generation,
        "started_at": row.started_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "discovered_count": row.discovered_count,
        "changed_count": row.changed_count,
        "unchanged_count": row.unchanged_count,
        "enqueued_count": row.enqueued_count,
        "skipped_count": row.skipped_count,
        "failed_count": row.failed_count,
        "failure_code": row.failure_code,
    }
