"""
Unit tests for DynamicTaskPlanner and Human-in-the-Loop (HITL) execution.
"""

import pytest
from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.planner import DynamicTaskPlanner, DynamicTaskPlan, TaskPlanItem


def test_dynamic_task_planner_complex_prompt(client: SuperDocsClient):
    planner = DynamicTaskPlanner(client=client)
    prompt = (
        "Create a Cloud Disaster Recovery Runbook with RPO and RTO objectives, "
        "AWS and Azure failover procedures, and DNS cutover instructions."
    )
    plan: DynamicTaskPlan = planner.evaluate_and_plan(prompt=prompt)

    assert plan.is_complex is True
    assert len(plan.tasks) >= 3
    assert plan.approval_status == "pending_review"
    
    # Verify prompt-specific task titles exist
    titles = [t.title.lower() for t in plan.tasks]
    assert any("disaster recovery" in t or "failover" in t or "rpo" in t or "structure" in t for t in titles)


def test_dynamic_task_planner_simple_prompt(client: SuperDocsClient):
    planner = DynamicTaskPlanner(client=client)
    prompt = "Fix typo in section 2"
    plan: DynamicTaskPlan = planner.evaluate_and_plan(prompt=prompt)

    assert plan.is_complex is False
    assert len(plan.tasks) == 1
    assert "Direct" in plan.tasks[0].phase or "Edit" in plan.tasks[0].title


def test_hitl_approval_and_execution_lifecycle(client: SuperDocsClient):
    planner = DynamicTaskPlanner(client=client)
    prompt = "Draft an AI Governance Policy with risk tiering and human oversight"
    plan: DynamicTaskPlan = planner.evaluate_and_plan(prompt=prompt)

    # 1. Verify initially unapproved
    assert plan.approval_status == "pending_review"
    unapproved_exec = planner.execute_approved_plan(plan.plan_id)
    assert unapproved_exec.success is False
    assert unapproved_exec.error == "ApprovalRequired"

    # 2. User modifies and approves the plan
    edited_tasks = [
        {
            "step": 1,
            "id": "TASK-1",
            "phase": "Planning",
            "title": "Define AI Governance Scope",
            "description": "Establish governance framework and oversight roles",
            "tool": "superdocs_chat",
        },
        {
            "step": 2,
            "id": "TASK-2",
            "phase": "Drafting",
            "title": "Formulate Risk Tiering Matrix",
            "description": "Create high, medium, and low risk AI classification table",
            "tool": "superdocs_chat",
        },
    ]
    approval_res = planner.approve_plan(plan_id=plan.plan_id, edited_tasks=edited_tasks)
    assert approval_res.success is True
    assert approval_res.data["approval_status"] == "approved"
    assert len(approval_res.data["tasks"]) == 2

    # 3. Execute approved plan
    exec_res = planner.execute_approved_plan(plan.plan_id)
    assert exec_res.success is True
    assert len(exec_res.data["tasks"]) == 2
    assert all(t["status"] == "completed" for t in exec_res.data["tasks"])
