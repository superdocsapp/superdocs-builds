import asyncio
import logging

from docrelay.core.config import get_settings
from docrelay.core.logging import configure_logging
from docrelay.integrations.google.runtime import GoogleRuntime
from docrelay.integrations.superdocs.runtime import SuperDocsRuntime
from docrelay.persistence.database import Database
from docrelay.services.artifacts import FilesystemArtifactStore
from docrelay.services.superdocs_workflow import SuperDocsWorkflow, SuperDocsWorkflowError
from docrelay.services.watch import WatchError, WatchService, build_watch_service

logger = logging.getLogger(__name__)


async def run_once(
    orchestrator: SuperDocsWorkflow,
    watcher: WatchService | None = None,
    *,
    watch_claim_limit: int = 10,
) -> int:
    work_count = 0
    if watcher is not None:
        claims = await watcher.claim_due(limit=watch_claim_limit)
        for claim in claims:
            try:
                await watcher.execute_claim(claim)
            except WatchError as exc:
                logger.warning(
                    "watch_worker_attention",
                    extra={
                        "safe_metadata": {
                            "watch_config_id": str(claim.watch_config_id),
                            "watch_scan_id": str(claim.scan_id),
                            "error_code": exc.code,
                        }
                    },
                )
            except Exception:
                logger.exception(
                    "watch_worker_failure",
                    extra={"safe_metadata": {"watch_scan_id": str(claim.scan_id)}},
                )
        work_count += len(claims)
    run_ids = await orchestrator.list_resumable_run_ids()
    for run_id in run_ids:
        try:
            await orchestrator.resume(run_id)
        except SuperDocsWorkflowError as exc:
            logger.warning(
                "phase3_worker_attention",
                extra={
                    "safe_metadata": {
                        "run_id": str(run_id),
                        "error_code": exc.code,
                    }
                },
            )
        except Exception:
            logger.exception(
                "phase3_worker_failure",
                extra={"safe_metadata": {"run_id": str(run_id)}},
            )
    return work_count + len(run_ids)


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    superdocs_runtime = SuperDocsRuntime.from_settings(settings)
    if superdocs_runtime is None:
        raise RuntimeError("SUPERDOCS_API_KEY is required for the SuperDocs workflow worker")
    google_runtime = GoogleRuntime.from_settings(settings)
    database = Database(settings.database_url)
    artifacts = FilesystemArtifactStore(settings.docrelay_artifact_dir)
    orchestrator = SuperDocsWorkflow(
        sessions=database.sessions,
        superdocs=superdocs_runtime.client,
        artifacts=artifacts,
        owner_subject=settings.docrelay_owner_subject,
    )
    watcher = (
        build_watch_service(
            sessions=database.sessions,
            owner_subject=settings.docrelay_owner_subject,
            runtime=google_runtime,
            runs=orchestrator,
            state_ttl_seconds=settings.google_oauth_state_ttl_seconds,
            refresh_skew_seconds=settings.google_access_token_refresh_skew_seconds,
            baseline_max_attempts=settings.google_baseline_max_attempts,
            scan_lease_seconds=settings.watch_scan_lease_seconds,
            max_items_per_scan=settings.watch_max_items_per_scan,
        )
        if google_runtime is not None
        else None
    )
    idle_multiplier = 1.0
    try:
        while True:
            work_count = await run_once(
                orchestrator,
                watcher,
                watch_claim_limit=settings.watch_worker_claim_limit,
            )
            idle_multiplier = 1.0 if work_count else min(idle_multiplier * 1.5, 5.0)
            await asyncio.sleep(settings.superdocs_worker_poll_seconds * idle_multiplier)
    finally:
        if google_runtime is not None:
            await google_runtime.close()
        await superdocs_runtime.close()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
