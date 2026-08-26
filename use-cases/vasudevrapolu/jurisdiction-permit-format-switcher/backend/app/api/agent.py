import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db, SessionLocal
from app.models.run import AgentRun
from app.schemas.agent import StartRunRequest, ApprovalRequest
from app.services.agent_runner import AgentRunner

router=APIRouter(prefix="/api/agent", tags=["agent"])

def serialize(row: AgentRun):
    state=json.loads(row.state_json)
    return {"id":row.id,"status":row.status,"current_stage":row.current_stage,"spent_ms":row.spent_ms,"state":state}

@router.post("/runs")
def create_run(req: StartRunRequest, background_tasks: BackgroundTasks, db: Session=Depends(get_db)):
    runner=AgentRunner(db); run_id=runner.start(req.documents,req.rules)
    background_tasks.add_task(AgentRunner, db) if False else None
    def work():
        with SessionLocal() as task_db:
            AgentRunner(task_db).execute(run_id)
    background_tasks.add_task(work)
    return {"run_id":run_id}

@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session=Depends(get_db)):
    row=db.get(AgentRun,run_id)
    if not row: raise HTTPException(404,"Run not found")
    return serialize(row)

@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str, req: ApprovalRequest, db: Session=Depends(get_db)):
    row=db.get(AgentRun,run_id)
    if not row: raise HTTPException(404,"Run not found")
    AgentRunner(db).approve(run_id, req.decisions)
    return serialize(db.get(AgentRun, run_id))
