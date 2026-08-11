import pytest
import uuid
from backend.app.services.workflow import compile_diligence_workflow, SQLAlchemyCheckpointer
from backend.app.services.ingestion import IngestionService
from tests.test_integration import AsyncTestSession
from backend.app.database import engine

def test_checkpointer_initialization():
    """
    Test 1: Checkpointer initializes successfully with db engine.
    """
    checkpointer = SQLAlchemyCheckpointer(engine)
    assert checkpointer.engine == engine

def test_workflow_state_checkpoint_persistence_and_resume():
    """
    Test 2-7: State, thread ID, evidence, and citations are persisted and
    correctly preserved upon workflow resumption on the same thread.
    """
    with AsyncTestSession() as ts:
        # Ingest document
        ingestion = IngestionService(ts.session)
        doc = ts.run(ingestion.ingest_document("sec.txt", b"SuperDocs security compliance includes SOC2 Type II audits."))
        
        # Compile graph with SQLAlchemy checkpointer bound to test engine
        workflow = compile_diligence_workflow(ts.engine)
        
        thread_id = str(uuid.uuid4())
        config = {
            "configurable": {
                "thread_id": thread_id,
                "db": ts.session
            }
        }
        
        initial_state = {
            "question": "What is the SuperDocs security compliance posture and audits status?",
            "status": "pending"
        }
        
        # 1. Run until the human_review interrupt point
        ts.run(workflow.ainvoke(initial_state, config))
        
        # 2. Retrieve the persisted state tuple
        state_info = ts.run(workflow.aget_state(config))
        assert state_info is not None
        assert state_info.values["status"] == "answered"
        assert len(state_info.values["retrieved_evidence"]) > 0
        
        # Record chunk ID
        original_chunk_id = state_info.values["retrieved_evidence"][0].chunk_id
        
        # 3. Resume same workflow thread by updating review_required to False
        ts.run(workflow.aupdate_state(config, {"review_required": False}))
        ts.run(workflow.ainvoke(None, config))
        
        # 4. Fetch final finalized state
        final_info = ts.run(workflow.aget_state(config))
        assert final_info.values["status"] == "answered"
        assert len(final_info.values["citations"]) > 0
        assert final_info.values["citations"][0].chunk_id == original_chunk_id


def test_workflow_fresh_checkpointer_restoration():
    """
    Test 8: True persistent restoration lifecycle.
    Runs a workflow until the interrupt using workflow instance 1.
    Retrieves and resumes the workflow using workflow instance 2.
    """
    with AsyncTestSession() as ts:
        # Ingest document
        ingestion = IngestionService(ts.session)
        doc = ts.run(ingestion.ingest_document(
            "fresh_checkpoint.txt", 
            b"SuperDocs compliance parameters are verified for persistent checkpointing."
        ))
        
        # 1. Compile first workflow instance and run until interrupt
        workflow_1 = compile_diligence_workflow(ts.engine)
        
        thread_id = str(uuid.uuid4())
        config = {
            "configurable": {
                "thread_id": thread_id,
                "db": ts.session
            }
        }
        
        initial_state = {
            "question": "What are the compliance parameters for persistent checkpointing?",
            "status": "pending"
        }
        
        ts.run(workflow_1.ainvoke(initial_state, config))
        
        # Verify state is saved at the interrupt point
        state_info_1 = ts.run(workflow_1.aget_state(config))
        assert state_info_1 is not None
        assert state_info_1.values["status"] == "answered"
        assert state_info_1.next == ("human_review",)
        
        # 2. Compile second fresh workflow instance and check restoration
        workflow_2 = compile_diligence_workflow(ts.engine)
        
        # Recover state from database checkpointer
        state_info_2 = ts.run(workflow_2.aget_state(config))
        assert state_info_2 is not None
        assert state_info_2.values["status"] == "answered"
        assert state_info_2.values["question"] == initial_state["question"]
        assert state_info_2.next == ("human_review",)
        
        # 3. Update state and resume execution using the second fresh instance
        ts.run(workflow_2.aupdate_state(config, {"review_required": False}))
        ts.run(workflow_2.ainvoke(None, config))
        
        # 4. Verify workflow completes finalization and citations are retrieved
        final_info = ts.run(workflow_2.aget_state(config))
        assert final_info.values["status"] == "answered"
        assert len(final_info.values["citations"]) > 0
        assert final_info.next == ()
