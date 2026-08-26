import json
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.run import AgentRun

class AgentStore:
    def __init__(self, db: Session): self.db = db
    def create(self, run_id: str, state: dict) -> AgentRun:
        row = AgentRun(id=run_id, status="queued", state_json=json.dumps(state), current_stage=None)
        self.db.add(row); self.db.commit(); self.db.refresh(row); return row
    def get(self, run_id: str) -> AgentRun:
        row = self.db.get(AgentRun, run_id)
        if not row: raise KeyError(run_id)
        return row
    def save(self, row: AgentRun, state: dict, status: str, stage: str | None, spent_ms: int) -> AgentRun:
        row.state_json = json.dumps(state, ensure_ascii=False)
        row.status = status; row.current_stage = stage; row.spent_ms = spent_ms; row.updated_at = datetime.utcnow()
        self.db.commit(); self.db.refresh(row); return row
