from datetime import datetime, timezone
from uuid import UUID, uuid4
from typing import Optional
from core.db import insert
from core.models import TraceRecord


class TraceLogger:
    def __init__(self, run_id: UUID):
        self.run_id = run_id

    async def log(
        self,
        node: str,
        input_hash: str,
        decision: Optional[str] = None,
        evidence: Optional[dict] = None,
        tokens_in: Optional[int] = None,
        tokens_out: Optional[int] = None,
        superdocs_ops: int = 0,
        ms: int = 0,
    ):
        record = TraceRecord(
            id=uuid4(),
            run_id=self.run_id,
            node=node,
            input_hash=input_hash,
            decision=decision,
            evidence=evidence,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            superdocs_ops=superdocs_ops,
            ms=ms,
            ts=datetime.now(timezone.utc),
        )
        await insert("trace", record.model_dump())