import json
from datetime import datetime, timezone
from uuid import UUID
from core.models import IngestionJob


class Dispatcher:
    @staticmethod
    async def dispatch_ingestion(
        run_id: UUID, document_ids: list[UUID], agent: str = "agent_2"
    ) -> UUID:
        from core.db import insert, to_uuid

        payload = IngestionJob(run_id=run_id, document_ids=document_ids)
        row = await insert(
            "jobs",
            {
                "kind": "ingestion",
                "agent": agent,
                "payload": json.dumps(payload.model_dump(mode="json"), default=str),
                "status": "pending",
                "created_at": datetime.now(timezone.utc),
            },
            returning="id",
        )
        return to_uuid(row["id"])