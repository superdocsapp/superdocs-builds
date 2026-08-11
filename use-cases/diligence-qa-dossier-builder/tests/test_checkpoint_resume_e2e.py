import pytest
import uuid
from sqlalchemy import text

from backend.app.services.ingestion import IngestionService
from backend.app.services.workflow import compile_diligence_workflow
import backend.app.services.workflow as workflow_module
from tests.test_integration import AsyncTestSession

def test_checkpoint_resume_e2e():
    """
    E2E integration test for graph execution interruption and state resumption.
    1. Ingests a synthetic document and builds the workflow graph using the PostgreSQL checkpointer.
    2. Spies on node executions by monkeypatching the functions directly.
    3. Patches the retrieval node to raise an exception on its first execution, simulating a crash.
    4. Triggers execution and verifies it aborts.
    5. Confirms that a valid checkpoint was stored in PostgreSQL.
    6. Triggers resumption from the checkpoint and verifies execution completes up to the human review gate.
    7. Asserts that the prior node (Query Analysis) was NOT re-executed (proving no duplicate work).
    8. Asserts that the final finding, citations, and evidence are correctly generated.
    """
    with AsyncTestSession() as ts:
        # 1. Ingest synthetic document
        ingestion = IngestionService(ts.session)
        doc = ts.run(ingestion.ingest_document(
            "diligence_source.txt",
            b"SuperDocs complies with SOC2 Type II guidelines and uses AES-256 data encryption."
        ))
        assert doc.status == "completed"

        thread_id = str(uuid.uuid4())
        config = {
            "configurable": {
                "db": ts.session,
                "thread_id": thread_id
            }
        }
        initial_state = {
            "question": "What is SuperDocs target SOC2 Type II compliance posture?",
            "status": "pending"
        }

        # Setup original references for cleanup
        orig_query_analysis = workflow_module.query_analysis_node
        orig_retrieval = workflow_module.retrieval_node

        query_analysis_calls = 0
        retrieval_calls = 0

        # Define spies matching the exact signatures and type annotations expected by LangGraph
        def spy_query_analysis(state: workflow_module.DiligenceWorkflowState) -> dict:
            nonlocal query_analysis_calls
            query_analysis_calls += 1
            return orig_query_analysis(state)

        async def spy_retrieval(state: workflow_module.DiligenceWorkflowState, config: workflow_module.RunnableConfig) -> dict:
            nonlocal retrieval_calls
            retrieval_calls += 1
            if retrieval_calls == 1:
                # Simulate a crash/interruption during this node execution
                raise RuntimeError("Simulated workflow interruption/crash!")
            return await orig_retrieval(state, config)

        try:
            # 2. Assign the spied functions directly to the module
            workflow_module.query_analysis_node = spy_query_analysis
            workflow_module.retrieval_node = spy_retrieval

            # Compile the workflow to bind the spied nodes
            workflow = compile_diligence_workflow(db_engine=ts.engine)
            
            # Execute first run and assert it raises the RuntimeError crash
            with pytest.raises(RuntimeError) as exc_info:
                ts.run(workflow.ainvoke(initial_state, config))
            
            assert "Simulated workflow interruption/crash!" in str(exc_info.value)

            # 3. Assertions after interruption
            # Query analysis ran once and succeeded
            assert query_analysis_calls == 1
            # Retrieval crashed on its first call
            assert retrieval_calls == 1

            # 4. Verify PostgreSQL checkpoint storage exists for this thread
            async def fetch_checkpoints():
                async with ts.engine.connect() as conn:
                    res = await conn.execute(
                        text("SELECT COUNT(*) FROM langgraph_checkpoints WHERE thread_id = :thread_id"),
                        {"thread_id": thread_id}
                    )
                    return res.scalar()
            
            checkpoints_count = ts.run(fetch_checkpoints())
            assert checkpoints_count > 0

            # 5. Restart/Resume execution from the exact same thread configuration
            # Re-assign retrieval node to a resume handler that does not raise errors
            async def spy_retrieval_resume(state: workflow_module.DiligenceWorkflowState, config: workflow_module.RunnableConfig) -> dict:
                nonlocal retrieval_calls
                retrieval_calls += 1
                return await orig_retrieval(state, config)

            workflow_module.retrieval_node = spy_retrieval_resume
            
            # Recompile the workflow to bind the resumption spied node
            workflow_resume = compile_diligence_workflow(db_engine=ts.engine)
            
            # Resume by invoking with None state, utilizing the saved thread_id checkpoint
            ts.run(workflow_resume.ainvoke(None, config))

            # 6. Assertions after resumption
            # Query analysis MUST NOT have been re-executed (spied count remains 1)
            assert query_analysis_calls == 1
            # Retrieval was executed again (resumed + ran successfully, spied count becomes 2)
            assert retrieval_calls == 2

            # 7. Verify the final finding was produced correctly and reached the human review pause state
            state_info = ts.run(workflow_resume.aget_state(config))
            state_values = state_info.values

            assert state_values["status"] == "answered"
            assert "SOC2 Type II" in state_values["draft_answer"]
            assert len(state_values["citations"]) > 0
            assert state_values["citations"][0].filename == "diligence_source.txt"
            
            # Confirms it paused before the next human review node (checkpoint next points to human_review)
            assert state_info.next == ("human_review",)

        finally:
            # Restore the original functions to avoid side-effects in other tests
            workflow_module.query_analysis_node = orig_query_analysis
            workflow_module.retrieval_node = orig_retrieval
