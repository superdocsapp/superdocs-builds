import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db, engine
from backend.app.models import Dossier, DossierFinding, FindingExecutionHistory, WorkflowExecutionMetric
from backend.app.schemas import (
    DossierCreate,
    DossierResponse,
    DossierQuestionRequest,
    DossierFindingResponse,
    ReviewActionRequest,
    Evidence,
    Citation,
    StageMetric,
    DossierMetricsResponse
)
from backend.app.services.workflow import compile_diligence_workflow

router = APIRouter(prefix="/dossiers", tags=["dossiers"])

# HELPER FUNCTIONS

async def update_dossier_status(dossier_id: uuid.UUID, db: AsyncSession):
    """
    Recalculates and updates the status of a dossier based on its findings' states.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.dossier_id == dossier_id))
    findings = res.scalars().all()
    
    if not findings:
        new_status = "pending"
    else:
        statuses = [f.status for f in findings]
        review_statuses = [f.review_status for f in findings]
        
        if "running" in statuses:
            new_status = "running"
        elif "pending" in statuses:
            new_status = "running"
        elif "pending" in review_statuses:
            new_status = "review_required"
        elif "failed" in statuses:
            new_status = "failed"
        else:
            new_status = "completed"
            
    await db.execute(
        text("UPDATE dossiers SET status = :status, updated_at = :now WHERE id = :id"),
        {"status": new_status, "now": datetime.now(timezone.utc), "id": dossier_id}
    )
    await db.commit()

def serialize_state_items(items: list) -> Optional[list]:
    if not items:
        return []
    
    def json_friendly(val):
        if isinstance(val, uuid.UUID):
            return str(val)
        if isinstance(val, dict):
            return {k: json_friendly(v) for k, v in val.items()}
        if isinstance(val, list):
            return [json_friendly(x) for x in val]
        return val

    serialized = []
    for item in items:
        if hasattr(item, "model_dump"):
            serialized.append(json_friendly(item.model_dump(mode="json")))
        else:
            serialized.append(json_friendly(item))
    return serialized

async def save_finding_state(finding: DossierFinding, current_state: Dict[str, Any], review_status: str, completed: bool, db: AsyncSession):
    """
    Helper that copies LangGraph state values back into the DossierFinding database record.
    """
    finding.status = current_state.get("status", finding.status)
    finding.review_status = review_status
    finding.answer = current_state.get("draft_answer")
    finding.confidence = current_state.get("confidence")
    finding.reasoning_summary = current_state.get("reasoning_summary")
    
    # Serialize evidence and citation models to JSON columns
    finding.citations = serialize_state_items(current_state.get("citations", []))
    finding.supporting_evidence = serialize_state_items(current_state.get("supporting_evidence", []))
    finding.contradicting_evidence = serialize_state_items(current_state.get("contradicting_evidence", []))
    
    if completed:
        finding.completed_at = datetime.now(timezone.utc)
    else:
        finding.completed_at = None
        
    finding.updated_at = datetime.now(timezone.utc)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)

# REST ENDPOINTS

@router.post("", response_model=DossierResponse, status_code=status.HTTP_201_CREATED)
async def create_dossier(payload: DossierCreate, db: AsyncSession = Depends(get_db)):
    """
    Creates a new dossier record.
    """
    dossier = Dossier(
        name=payload.name,
        status="pending"
    )
    db.add(dossier)
    await db.commit()
    await db.refresh(dossier)
    
    # Local ID assignment and session expunge
    dossier_id = dossier.id
    db.expunge(dossier)
    
    # Reload with empty findings list eagerly loaded
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == dossier_id)
    )
    return res.scalar()

@router.get("", response_model=List[DossierResponse])
async def list_dossiers(db: AsyncSession = Depends(get_db)):
    """
    Lists all dossiers in the system.
    """
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).order_by(Dossier.created_at.desc())
    )
    return res.scalars().all()

@router.post("/{dossier_id}/questions", response_model=DossierResponse)
async def add_dossier_questions(
    dossier_id: uuid.UUID,
    payload: DossierQuestionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Appends a batch of questions to a dossier, creating independent finding records.
    """
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == dossier_id)
    )
    dossier = res.scalar()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier not found.")
        
    for q in payload.questions:
        finding = DossierFinding(
            dossier_id=dossier.id,
            question=q,
            status="pending",
            review_status="not_required",
            workflow_thread_id=str(uuid.uuid4())
        )
        db.add(finding)
        
    await db.commit()
    await update_dossier_status(dossier.id, db)
    
    # Local ID assignment and session expunge
    d_id = dossier.id
    db.expunge(dossier)
    
    # Return reloaded dossier
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == d_id)
    )
    return res.scalar()

@router.post("/{dossier_id}/run", response_model=DossierResponse)
async def run_dossier_findings(dossier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Runs all pending or failed findings in the dossier sequentially, maintaining isolation.
    """
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == dossier_id)
    )
    dossier = res.scalar()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier not found.")
        
    res_f = await db.execute(select(DossierFinding).where(DossierFinding.dossier_id == dossier.id))
    findings = res_f.scalars().all()
    
    workflow = compile_diligence_workflow(db.bind)
    
    for finding in findings:
        # Run only findings that need execution (pending, failed)
        if finding.status not in ["pending", "failed"]:
            continue
            
        finding.status = "running"
        finding.started_at = datetime.now(timezone.utc)
        db.add(finding)
        await db.commit()
        
        config = {
            "configurable": {
                "thread_id": finding.workflow_thread_id,
                "db": db,
                "dossier_id": dossier.id,
                "finding_id": finding.id
            }
        }
        
        initial_state = {
            "question": finding.question,
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
        
        try:
            # 1. Start Graph execution
            await workflow.ainvoke(initial_state, config)
            
            # 2. Get state snapshot at termination/interrupt point
            state_info = await workflow.aget_state(config)
            current_state = state_info.values
            next_nodes = state_info.next
            
            if next_nodes and "human_review" in next_nodes:
                # Interrupted for human review
                review_required = current_state.get("review_required", False)
                
                if review_required or current_state.get("status") == "conflict" or current_state.get("confidence", 0.0) < 0.60:
                    # Suspend execution at this checkpoint
                    await save_finding_state(finding, current_state, review_status="pending", completed=False, db=db)
                else:
                    # Auto-resume graph (review not required)
                    await workflow.ainvoke(None, config)
                    final_info = await workflow.aget_state(config)
                    await save_finding_state(finding, final_info.values, review_status="not_required", completed=True, db=db)
            else:
                # Ran to completion
                await save_finding_state(finding, current_state, review_status="not_required", completed=True, db=db)
                
        except Exception as e:
            # Shield graph node failures
            finding.status = "failed"
            finding.completed_at = datetime.now(timezone.utc)
            finding.reasoning_summary = f"Workflow failed: {str(e)}"
            db.add(finding)
            await db.commit()
            
    await update_dossier_status(dossier.id, db)
    
    # Local ID assignment and session expunge
    d_id = dossier.id
    db.expunge(dossier)
    
    # Return reloaded dossier
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == d_id)
    )
    return res.scalar()

@router.get("/{dossier_id}", response_model=DossierResponse)
async def get_dossier(dossier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Retrieves the dossier and all nested findings.
    """
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == dossier_id)
    )
    dossier = res.scalar()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier not found.")
    return dossier

@router.get("/{dossier_id}/export", response_class=PlainTextResponse)
async def export_dossier_markdown(dossier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Exports the dossier and all its findings as a Markdown report.
    """
    res = await db.execute(
        select(Dossier).options(selectinload(Dossier.findings)).where(Dossier.id == dossier_id)
    )
    dossier = res.scalar()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier not found.")

    lines = []
    lines.append(f"# Diligence Dossier Report: {dossier.name}")
    lines.append(f"**Exported on (UTC)**: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Overall Status**: {dossier.status.replace('_', ' ').title()}")
    lines.append(f"**Dossier ID**: {dossier.id}")
    lines.append("")

    lines.append("## Diligence Findings Summary")
    if not dossier.findings:
        lines.append("*No findings exist in this dossier.*")
    else:
        lines.append("| Question | Workflow Status | Governance Status | Confidence |")
        lines.append("|---|---|---|---|")
        for f in dossier.findings:
            conf_str = f"{int(f.confidence * 100)}%" if f.confidence is not None else "N/A"
            lines.append(f"| {f.question} | {f.status.upper()} | {f.review_status.upper()} | {conf_str} |")
    lines.append("")

    lines.append("## Detailed Findings and Evidence")
    for idx, f in enumerate(dossier.findings, 1):
        lines.append(f"### {idx}. {f.question}")
        lines.append(f"* **Workflow Status**: {f.status.replace('_', ' ').upper()}")
        lines.append(f"* **Governance Status**: {f.review_status.replace('_', ' ').upper()}")
        conf_str = f"{int(f.confidence * 100)}%" if f.confidence is not None else "N/A"
        lines.append(f"* **Confidence Level**: {conf_str}")
        lines.append(f"* **Answer**: {f.answer if f.answer else 'No answer generated.'}")
        lines.append(f"* **Reasoning Summary**: {f.reasoning_summary if f.reasoning_summary else 'No reasoning summary provided.'}")
        if f.review_reason:
            lines.append(f"* **Reviewer Notes/Decision Details**: {f.review_reason}")
        lines.append("")

        # Gaps / Unresolved Handling
        if f.status == "insufficient_evidence":
            lines.append("> [!WARNING]")
            lines.append("> **Unresolved Diligence Gap**: Evidence was found to be insufficient to answer this question.")
            lines.append("")

        # Citations / Evidence
        lines.append("#### Grounded Evidence:")
        citations = f.citations or []
        if not citations:
            lines.append("*Evidence was not found in the data room documents.*")
        else:
            for cit in citations:
                filename = cit.get("filename", "unknown_file")
                sec = cit.get("section") or "N/A"
                page = cit.get("page_number") or "N/A"
                excerpt = cit.get("excerpt") or ""
                lines.append(f"- **File**: `{filename}` | **Section**: `{sec}` | **Page**: `{page}`")
                if excerpt:
                    lines.append(f"  *Excerpt*: \"{excerpt}\"")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)

@router.get("/{dossier_id}/findings/{finding_id}", response_model=DossierFindingResponse)
async def get_dossier_finding(
    dossier_id: uuid.UUID,
    finding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves details of an individual finding, validating cross-dossier integrity.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.id == finding_id))
    finding = res.scalar()
    if not finding or finding.dossier_id != dossier_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Finding not found or does not belong to this dossier."
        )
    return finding

# REVIEW ENDPOINTS

@router.post("/{dossier_id}/findings/{finding_id}/approve", response_model=DossierFindingResponse)
async def approve_finding(
    dossier_id: uuid.UUID,
    finding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Approves finding, resuming the graph thread and completing finalization.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.id == finding_id))
    finding = res.scalar()
    if not finding or finding.dossier_id != dossier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found.")
        
    if finding.review_status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Finding is not awaiting review.")
        
    workflow = compile_diligence_workflow(db.bind)
    config = {
        "configurable": {
            "thread_id": finding.workflow_thread_id,
            "db": db,
            "dossier_id": dossier_id,
            "finding_id": finding_id
        }
    }
    
    # Update state value to disable review gate pause
    await workflow.aupdate_state(config, {"review_required": False})
    
    # Resume the same graph thread
    await workflow.ainvoke(None, config)
    
    state_info = await workflow.aget_state(config)
    current_state = state_info.values
    
    # Update database record
    finding.review_status = "approved"
    if finding.status != "conflict":
        finding.status = "answered"
    finding.completed_at = datetime.now(timezone.utc)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    
    await update_dossier_status(dossier_id, db)
    return finding

@router.post("/{dossier_id}/findings/{finding_id}/reject", response_model=DossierFindingResponse)
async def reject_finding(
    dossier_id: uuid.UUID,
    finding_id: uuid.UUID,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Rejects finding, setting review_status = rejected, preserving audit findings,
    and bypassing further workflow execution.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.id == finding_id))
    finding = res.scalar()
    if not finding or finding.dossier_id != dossier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found.")
        
    if finding.review_status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Finding is not awaiting review.")
        
    finding.review_status = "rejected"
    finding.review_reason = payload.reason or "Rejected by reviewer."
    finding.completed_at = datetime.now(timezone.utc)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    
    await update_dossier_status(dossier_id, db)
    return finding

@router.post("/{dossier_id}/findings/{finding_id}/edit", response_model=DossierFindingResponse)
async def edit_finding(
    dossier_id: uuid.UUID,
    finding_id: uuid.UUID,
    payload: ReviewActionRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Allows a reviewer to edit the answer/reasoning summary, updating the graph state
    and resuming toward finalization without modifying the underlying cited evidence.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.id == finding_id))
    finding = res.scalar()
    if not finding or finding.dossier_id != dossier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found.")
        
    if finding.review_status != "pending":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Finding is not awaiting review.")
        
    if not payload.answer or not payload.reasoning_summary:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Answer and reasoning_summary are required for edits."
        )
        
    workflow = compile_diligence_workflow(db.bind)
    config = {
        "configurable": {
            "thread_id": finding.workflow_thread_id,
            "db": db,
            "dossier_id": dossier_id,
            "finding_id": finding_id
        }
    }
    
    # Update answer/reasoning and override review required flag
    await workflow.aupdate_state(config, {
        "draft_answer": payload.answer,
        "reasoning_summary": payload.reasoning_summary,
        "review_required": False
    })
    
    # Resume workflow
    await workflow.ainvoke(None, config)
    
    # Save edits back to DB finding
    finding.review_status = "edited"
    finding.answer = payload.answer
    finding.reasoning_summary = payload.reasoning_summary
    if finding.status != "conflict":
        finding.status = "answered"
    finding.completed_at = datetime.now(timezone.utc)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    
    await update_dossier_status(dossier_id, db)
    return finding

@router.post("/{dossier_id}/findings/{finding_id}/retry", response_model=DossierFindingResponse)
async def retry_finding(
    dossier_id: uuid.UUID,
    finding_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    Reruns the finding workflow using a new thread ID, saving the historical run
    to the audit history table first.
    """
    res = await db.execute(select(DossierFinding).where(DossierFinding.id == finding_id))
    finding = res.scalar()
    if not finding or finding.dossier_id != dossier_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found.")
        
    if finding.status == "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot retry a currently executing finding.")
        
    # 1. Audit trail log
    history = FindingExecutionHistory(
        finding_id=finding.id,
        workflow_thread_id=finding.workflow_thread_id,
        status=finding.status,
        answer=finding.answer,
        confidence=finding.confidence,
        reasoning_summary=finding.reasoning_summary,
        citations=finding.citations
    )
    db.add(history)
    
    # 2. Re-initialize finding columns for the fresh run
    new_thread_id = str(uuid.uuid4())
    finding.workflow_thread_id = new_thread_id
    finding.status = "running"
    finding.review_status = "not_required"
    finding.answer = None
    finding.confidence = None
    finding.reasoning_summary = None
    finding.citations = None
    finding.supporting_evidence = None
    finding.contradicting_evidence = None
    finding.review_reason = None
    finding.started_at = datetime.now(timezone.utc)
    finding.completed_at = None
    
    db.add(finding)
    await db.commit()
    
    # 3. Start execution on new thread
    workflow = compile_diligence_workflow(db.bind)
    config = {
        "configurable": {
            "thread_id": new_thread_id,
            "db": db,
            "dossier_id": dossier_id,
            "finding_id": finding_id
        }
    }
    
    initial_state = {
        "question": finding.question,
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
    
    try:
        await workflow.ainvoke(initial_state, config)
        
        state_info = await workflow.aget_state(config)
        current_state = state_info.values
        next_nodes = state_info.next
        
        if next_nodes and "human_review" in next_nodes:
            review_required = current_state.get("review_required", False)
            if review_required or current_state.get("status") == "conflict" or current_state.get("confidence", 0.0) < 0.60:
                await save_finding_state(finding, current_state, review_status="pending", completed=False, db=db)
            else:
                await workflow.ainvoke(None, config)
                final_info = await workflow.aget_state(config)
                await save_finding_state(finding, final_info.values, review_status="not_required", completed=True, db=db)
        else:
            await save_finding_state(finding, current_state, review_status="not_required", completed=True, db=db)
            
    except Exception as e:
        finding.status = "failed"
        finding.completed_at = datetime.now(timezone.utc)
        finding.reasoning_summary = f"Retry workflow failed: {str(e)}"
        db.add(finding)
        await db.commit()
        
    await update_dossier_status(dossier_id, db)
    
    # Reload and return updated finding
    res_reload = await db.execute(select(DossierFinding).where(DossierFinding.id == finding.id))
    return res_reload.scalar()


@router.get("/{dossier_id}/metrics", response_model=DossierMetricsResponse)
async def get_dossier_metrics(dossier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """
    Retrieves and aggregates execution metrics for a specific dossier.
    Enforces strict dossier isolation.
    """
    # 1. Dossier validation
    res_d = await db.execute(select(Dossier).where(Dossier.id == dossier_id))
    dossier = res_d.scalar()
    if not dossier:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dossier not found")

    # 2. Query metrics
    res_m = await db.execute(
        select(WorkflowExecutionMetric)
        .where(WorkflowExecutionMetric.dossier_id == dossier_id)
        .order_by(WorkflowExecutionMetric.created_at.asc())
    )
    metrics = res_m.scalars().all()

    # 3. Aggregate metrics
    total_duration = sum(m.duration_ms for m in metrics)
    total_input = sum(m.input_tokens for m in metrics if m.input_tokens is not None)
    total_output = sum(m.output_tokens for m in metrics if m.output_tokens is not None)
    total_estimated_cost = sum(m.estimated_cost for m in metrics if m.estimated_cost is not None)
    
    successful = sum(1 for m in metrics if m.status == "success")
    failed = sum(1 for m in metrics if m.status == "failed")
    
    models = list(set(m.model_name for m in metrics if m.model_name))
    providers = list(set(m.provider_name for m in metrics if m.provider_name))

    stages = [
        StageMetric(
            stage_name=m.stage_name,
            status=m.status,
            duration_ms=m.duration_ms,
            input_tokens=m.input_tokens,
            output_tokens=m.output_tokens,
            model_name=m.model_name,
            provider_name=m.provider_name,
            estimated_cost=m.estimated_cost,
            error_message=m.error_message,
            start_time=m.start_time,
            end_time=m.end_time
        )
        for m in metrics
    ]

    return DossierMetricsResponse(
        dossier_id=dossier_id,
        total_duration_ms=total_duration,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        total_tokens=total_input + total_output,
        estimated_total_cost=round(total_estimated_cost, 6),
        successful_stages=successful,
        failed_stages=failed,
        models_used=models,
        providers_used=providers,
        stages=stages
    )
