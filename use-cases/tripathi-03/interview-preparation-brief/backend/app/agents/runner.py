"""Run the LangGraph brief pipeline and persist results."""

from __future__ import annotations

from uuid import UUID

from app.agents.contracts import NO_EVIDENCE
from app.agents.graph import build_validated_brief_graph
from app.agents.state import BriefState
from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.session import AsyncSessionLocal
from app.services.brief.brief_service import BriefService

logger = get_logger(__name__)


async def run_brief_pipeline(brief_id: UUID, session_id: UUID) -> None:
    settings = get_settings()
    graph = build_validated_brief_graph()

    async with AsyncSessionLocal() as db:
        service = BriefService(db, settings)
        try:
            await service.mark_running(brief_id, "ResumeParser")
            inputs = await service.load_graph_inputs(session_id)
            initial: BriefState = {
                **inputs,
                "brief_id": str(brief_id),
                "evidence_fallback": settings.evidence_fallback or NO_EVIDENCE,
                "current_step": "starting",
                "error": None,
            }

            final_state: BriefState = dict(initial)
            async for event in graph.astream(initial, stream_mode="updates"):
                for node_name, update in event.items():
                    final_state.update(update)
                    step = update.get("current_step") or node_name
                    logger.info("Brief %s completed node=%s", brief_id, node_name)
                    await service.mark_running(brief_id, step)
                    if update.get("error"):
                        raise RuntimeError(update["error"])

            report = final_state.get("report")
            if not report:
                raise RuntimeError(
                    "InterviewPreparationReport did not produce structured output"
                )

            await service.mark_completed(brief_id, report)
            logger.info("Brief %s completed successfully", brief_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Brief %s failed: %s", brief_id, exc)
            await service.mark_failed(brief_id, str(exc))
