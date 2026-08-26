import json, time
from sqlalchemy.orm import Session
from app.services.agent_store import AgentStore
from app.workflows.agent import AgentState, STAGES, ingest, extract, reconcile, compliance, plan_update, review, commit

NODE_MAP={"ingest":ingest,"extract":extract,"reconcile":reconcile,"compliance":compliance,"plan_update":plan_update,"review":review,"commit":commit}

class AgentRunner:
    def __init__(self, db: Session): self.db=db

    def start(self, documents, rules):
        from uuid import uuid4
        run_id=str(uuid4())
        state: AgentState={"run_id":run_id,"documents":[d.model_dump() for d in documents],"rules":[r.model_dump() for r in rules],"approved":{},"stage_log":[]}
        AgentStore(self.db).create(run_id,state)
        return run_id

    def _execute_from(self, run_id: str, start_stage: str):
        store=AgentStore(self.db); row=store.get(run_id); state=json.loads(row.state_json)
        started=time.perf_counter()
        store.save(row,state,"running",start_stage,row.spent_ms)
        start_index=STAGES.index(start_stage)
        try:
            for stage in STAGES[start_index:]:
                result=NODE_MAP[stage](state)
                state=result
                # Checkpoint after every stage. A killed process restarts from current_stage.
                if stage=="review" and state.get("stopped"):
                    store.save(row,state,"waiting_review","review",row.spent_ms+int((time.perf_counter()-started)*1000))
                    return state
                store.save(row,state,"running",stage,row.spent_ms+int((time.perf_counter()-started)*1000))
            store.save(row,state,"completed","commit",row.spent_ms+int((time.perf_counter()-started)*1000))
            return state
        except Exception as exc:
            state["error"]=str(exc)
            store.save(row,state,"failed",stage,row.spent_ms+int((time.perf_counter()-started)*1000))
            raise

    def execute(self, run_id: str):
        row=AgentStore(self.db).get(run_id)
        state=json.loads(row.state_json)
        if row.status=="waiting_review": return state
        start_stage=STAGES[min(STAGES.index(row.current_stage)+1, len(STAGES)-1)] if row.current_stage else "ingest"
        return self._execute_from(run_id,start_stage)

    def approve(self, run_id: str, decisions):
        store=AgentStore(self.db); row=store.get(run_id); state=json.loads(row.state_json)
        state["approved"]={d.id:d.approved for d in decisions}
        for d in decisions:
            if d.feedback: state.setdefault("feedback",{})[d.id]=d.feedback
        state["stopped"]=False
        store.save(row,state,"running","review",row.spent_ms)
        # Re-run review with the decisions, then continue into commit.
        state=review(state)
        if state.get("stopped"):
            store.save(row,state,"waiting_review","review",row.spent_ms)
            return state
        state=commit(state)
        store.save(row,state,"completed","commit",row.spent_ms)
        return state
