from fastapi import FastAPI
from agent_graph import app as graph_app

# The MCP (Model Context Protocol) server exposes our LangGraph pipeline 
# as tools that an LLM agent (like Claude or Cursor) can call directly.

app = FastAPI(title="SuperDocs Agent MCP Server")

@app.post("/mcp/tools/run_pipeline")
def run_pipeline(documents: list):
    """
    Triggers the end-to-end agentic pipeline for a set of documents.
    Stops at the human review gate.
    """
    initial_state = {
        "documents": documents,
        "pending_approval": False,
        "approved": False
    }
    
    # Run the graph until the human_review_gate
    final_state = graph_app.invoke(initial_state)
    return {"status": "Waiting for human review", "state": final_state}

@app.post("/mcp/tools/approve_changes")
def approve_changes(state: dict):
    """
    Resumes the pipeline after a human approves the changes.
    """
    state["pending_approval"] = False
    state["approved"] = True
    
    final_state = graph_app.invoke(state)
    return {"status": "Changes committed", "state": final_state}

@app.post("/mcp/tools/reject_changes")
def reject_changes(state: dict):
    """
    Resumes the pipeline after a human rejects the changes.
    """
    state["pending_approval"] = False
    state["approved"] = False
    
    final_state = graph_app.invoke(state)
    return {"status": "Changes rejected", "state": final_state}
