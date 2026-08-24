"""
Dynamic Prompt-Specific Task Planner & Human-in-the-Loop (HITL) Execution Demo.

Demonstrates:
1. Evaluating prompt complexity via SuperDocs AI.
2. Generating a tailored, prompt-specific task decomposition (not boilerplate).
3. Human-in-the-Loop (HITL) review and approval gate.
4. Executing approved tasks sequentially against SuperDocs Cloud API in session context.
"""

import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.planner import DynamicTaskPlanner


def main():
    print("=" * 80)
    print(" 🧠 SuperDocs Dynamic Agentic Planner & HITL Approval Demo")
    print("=" * 80)

    offline_mode = "--offline" in sys.argv
    client = SuperDocsClient(offline=offline_mode) if offline_mode else SuperDocsClient()
    planner = DynamicTaskPlanner(client=client)

    print(f"• Mode: {'Offline Mock' if client.offline else 'Live SuperDocs Cloud API'}")
    whoami = client.get_whoami()
    if whoami.success and whoami.data:
        d = whoami.data
        print(f"• Account: {d.get('account_id')} | Tier: {d.get('tier')} | Quota: {d.get('remaining')}/{d.get('monthly_limit')} ops left")
    print("-" * 80)

    # Prompt containing specific domain requirements
    prompt = (
        "Draft a Multi-Cloud Disaster Recovery Runbook for fintech services with: "
        "1. RTO/RPO objectives and failover triggers, "
        "2. AWS to GCP database replication & DNS cutover, "
        "3. Regulatory compliance checklist and post-incident review."
    )

    print(f"\n[Step 1] User Goal:\n\"{prompt}\"")
    print("\n[Step 2] Querying SuperDocs AI for Complexity Analysis & Task Decomposition...")

    plan = planner.evaluate_and_plan(prompt=prompt)

    print(f"\n✅ Synthesized Dynamic Plan:")
    print(f"   ↳ Plan ID       : {plan.plan_id}")
    print(f"   ↳ Document Type : {plan.document_type}")
    print(f"   ↳ Complexity    : {'COMPLEX (Multi-step staged execution)' if plan.is_complex else 'SIMPLE (Direct Edit)'}")
    print(f"   ↳ Rationale     : {plan.decision_rationale}")
    print(f"   ↳ Approval Gate : {plan.approval_status.upper()}")

    print("\n" + "=" * 80)
    print(" 📋 DECOMPOSED PROMPT-SPECIFIC TASK LIST (Awaiting HITL Review)")
    print("=" * 80)
    for t in plan.tasks:
        print(f"  [{t.id}] {t.title}")
        print(f"         Phase    : {t.phase} | Tool: {t.tool} | Est: {t.estimated_time}")
        print(f"         Details  : {t.description}")
        print(f"         Criteria : {t.acceptance_criteria}")
        print()

    # Step 3: HITL Approval Gate
    print("-" * 80)
    print("[Step 3] Human-in-the-Loop Approval Gate")
    
    user_choice = "y"
    if sys.stdin.isatty() and "--auto" not in sys.argv:
        try:
            prompt_input = input("\n👉 Review the plan above. [Y] Approve & Execute / [n] Reject / [e] Edit subtask: ").strip().lower()
            if prompt_input:
                user_choice = prompt_input
        except (EOFError, KeyboardInterrupt):
            user_choice = "y"

    if user_choice == "n":
        print("❌ Plan rejected by user. Aborting execution.")
        return
    elif user_choice == "e":
        print("\n✏️  Entering Quick Task Editor:")
        try:
            custom_title = input(f"Enter custom title for {plan.tasks[0].id} (or press Enter to keep '{plan.tasks[0].title}'): ").strip()
            if custom_title:
                plan.tasks[0].title = custom_title
                print(f"✓ Updated {plan.tasks[0].id} title to: {custom_title}")
        except (EOFError, KeyboardInterrupt):
            pass

    print(f"\nApproving task plan '{plan.plan_id}' for execution...")
    approval_res = planner.approve_plan(plan.plan_id, edited_tasks=[t.model_dump() for t in plan.tasks])
    print(f"✅ Status: {approval_res.message}")

    # Step 4: Live Sequential Task Execution
    print("\n[Step 4] Beginning Sequential Execution against SuperDocs Cloud API...")

    def on_progress(evt):
        task = evt.get("task") or {}
        status = evt.get("status") or "in_progress"
        step = evt.get("current_step") or 1
        total = evt.get("total_steps") or 1
        task_id = task.get("id") or "TASK"
        task_title = task.get("title") or evt.get("message") or ""
        print(f"   ↳ [Step {step}/{total}] [{task_id}] {task_title[:40]}... -> {status.upper()}")

    exec_res = planner.execute_approved_plan(plan.plan_id, progress_callback=on_progress)

    if exec_res.success:
        print("\n" + "=" * 80)
        print(" 🎉 All Dynamic Tasks Executed Successfully!")
        print("=" * 80)
        print(f"• Execution Summary:")
        for log in exec_res.data.get("execution_logs", []):
            print(f"  ✓ {log}")

        preview = (exec_res.data.get("export_markdown") or "")[:400]
        if preview:
            print(f"\n--- Final Document Preview ---\n{preview}\n...")
    else:
        print(f"\n❌ Execution finished with error: {exec_res.message}")


if __name__ == "__main__":
    main()

