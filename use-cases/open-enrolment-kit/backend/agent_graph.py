import operator
from typing import Annotated, TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
import psycopg
import requests
import time
import os
import logging
from database import DB_URI
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SUPERDOCS_API_KEY = os.getenv("SUPERDOCS_API_KEY")
SUPERDOCS_BASE_URL = "https://api.superdocs.app"

def get_sd_headers():
    return {
        "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
        "Content-Type": "application/json"
    }

class GraphState(TypedDict):
    job_id: str
    document_id: str
    instructions: str
    base_html: str
    superdocs_job_id: Optional[str]
    superdocs_session_id: Optional[str]
    status: str
    pending_changes: List[Dict[str, Any]]
    user_approval_payload: List[Dict[str, Any]]
    final_output: Optional[str]

def prepare_and_invoke(state: GraphState):
    logger.info("--- [START] Node: prepare_and_invoke ---")
    session_id = state.get("superdocs_session_id")
    if not session_id:
        session_id = state["job_id"]
        
    chat_res = requests.post(f"{SUPERDOCS_BASE_URL}/v1/chat/async", headers=get_sd_headers(), json={
        "message": state["instructions"],
        "session_id": session_id,
        "document_html": state["base_html"],
        "approval_mode": "ask_every_time"
    })
    
    if chat_res.status_code == 200:
        sd_job_id = chat_res.json()["job_id"]
        return {"superdocs_job_id": sd_job_id, "superdocs_session_id": session_id, "status": "invoked"}
    else:
        logger.error(f"SuperDocs API error: {chat_res.text}")
        return {"status": "failed"}

def poll_for_approval(state: GraphState):
    logger.info("--- [START] Node: poll_for_approval ---")
    sd_job_id = state.get("superdocs_job_id")
    

    while True:
        res = requests.get(f"{SUPERDOCS_BASE_URL}/v1/jobs/{sd_job_id}", headers=get_sd_headers())
        if res.status_code == 200:
            sd_job = res.json()
            status = sd_job.get("status")
            if status == "awaiting_approval":
                pending = sd_job.get("metadata", {}).get("pending_changes", [])
                return {"status": "awaiting_approval", "pending_changes": pending}
            elif status in ["completed", "failed"]:
                return {"status": status}
        time.sleep(3)

def wait_for_human(state: GraphState):
    logger.info("--- [START] Node: wait_for_human ---")

    return {"status": "pending_human"}

def process_approval(state: GraphState):
    logger.info("--- [START] Node: process_approval ---")
    sd_job_id = state.get("superdocs_job_id")
    session_id = state.get("superdocs_session_id")
    payload = state.get("user_approval_payload", [])
    
    changes_payload = []
    for item in payload:
        changes_payload.append({
            "change_id": item["item_id"],
            "approved": item["status"] == "approved"
        })
        
    approve_res = requests.post(f"{SUPERDOCS_BASE_URL}/v1/chat/{session_id}/approve", headers=get_sd_headers(), json={
        "job_id": sd_job_id,
        "approved": True, 
        "changes": changes_payload
    })
    
    if approve_res.status_code == 200:
        return {"status": "approved"}
    else:
        return {"status": "failed"}

def determine_post_invoke(state: GraphState):
    if state["status"] == "failed":
        return END
    return "poll_for_approval"

def determine_post_poll(state: GraphState):
    if state["status"] == "awaiting_approval":
        return "wait_for_human"
    return END

workflow = StateGraph(GraphState)
workflow.add_node("prepare_and_invoke", prepare_and_invoke)
workflow.add_node("poll_for_approval", poll_for_approval)
workflow.add_node("wait_for_human", wait_for_human)
workflow.add_node("process_approval", process_approval)

workflow.set_entry_point("prepare_and_invoke")
workflow.add_conditional_edges("prepare_and_invoke", determine_post_invoke)
workflow.add_conditional_edges("poll_for_approval", determine_post_poll)
workflow.add_edge("wait_for_human", "process_approval")
workflow.add_edge("process_approval", END)


from psycopg_pool import ConnectionPool
pool = ConnectionPool(DB_URI)
saver = PostgresSaver(pool)
saver.setup()

app = workflow.compile(checkpointer=saver, interrupt_before=["wait_for_human"])

if __name__ == "__main__":
    pass
