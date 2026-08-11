import uuid
from pydantic import BaseModel
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db, engine
from backend.app.schemas import AnswerResponse
from backend.app.services.workflow import compile_diligence_workflow

router = APIRouter(prefix="/questions", tags=["questions"])

class AnswerRequest(BaseModel):
    question: str

@router.post("/answer", response_model=AnswerResponse)
async def answer_question(
    payload: AnswerRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Answers a diligence question by invoking the compiled LangGraph workflow.
    Automatically resumes past the human review checkpoint for single-shot requests.
    """
    try:
        # 1. Compile workflow passing the engine for DB persistence
        workflow = compile_diligence_workflow(db.bind)

        # 2. Setup initial state and config with a unique thread ID
        thread_id = str(uuid.uuid4())
        config = {
            "configurable": {
                "thread_id": thread_id,
                "db": db
            }
        }
        
        initial_state = {
            "question": payload.question,
            "normalized_question": "",
            "retrieved_evidence": [],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "status": "pending",
            "draft_answer": "",
            "citations": [],
            "confidence": 0.0,
            "reasoning_summary": "",
            "review_required": False,
            "errors": None
        }

        # 3. Invoke initial graph execution
        await workflow.ainvoke(initial_state, config)

        # 4. Auto-resume loop if the graph interrupts at the human review node
        while True:
            state_info = await workflow.aget_state(config)
            if state_info.next:
                # Bypass the human review gate and resume
                await workflow.aupdate_state(config, {"review_required": False})
                await workflow.ainvoke(None, config)
            else:
                break

        # 5. Fetch final state values
        final_state_info = await workflow.aget_state(config)
        final_state = final_state_info.values

        # 6. Handle technical failures
        if final_state.get("status") == "failed":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=final_state.get("errors") or "Workflow execution failed."
            )

        return AnswerResponse(
            question=final_state["question"],
            answer=final_state["draft_answer"],
            status=final_state["status"],
            confidence=final_state["confidence"],
            citations=final_state["citations"],
            supporting_evidence=final_state["supporting_evidence"],
            contradicting_evidence=final_state["contradicting_evidence"],
            reasoning_summary=final_state["reasoning_summary"],
            created_at=datetime.now(timezone.utc)
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution uncaught crash: {str(e)}"
        )
