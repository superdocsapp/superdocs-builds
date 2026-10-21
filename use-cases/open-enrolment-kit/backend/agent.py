import json
import logging
from typing import TypedDict, Annotated, List, Dict
import operator

# Note: In a real implementation we would use LangGraph here.
# For simplicity in this demo, we simulate a state graph.

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    plan_2025: dict
    plan_2026: dict
    diff: List[dict]
    documents_to_update: List[str]
    instructions: List[str]

def load_plans(state: AgentState) -> AgentState:
    with open("d:/superdocs/data/plan_2025.json") as f:
        state["plan_2025"] = json.load(f)
    with open("d:/superdocs/data/plan_2026.json") as f:
        state["plan_2026"] = json.load(f)
    return state

def compute_diff(state: AgentState) -> AgentState:
    diff = []
    # simplified diffing logic
    for category, details in state["plan_2026"].items():
        if category in state["plan_2025"]:
            for key, val in details.items():
                old_val = state["plan_2025"][category].get(key)
                if old_val != val:
                    diff.append({
                        "category": category,
                        "key": key,
                        "old": old_val,
                        "new": val
                    })
        else:
            diff.append({"category": category, "status": "new", "details": details})
    state["diff"] = diff
    return state

def generate_instructions(state: AgentState) -> AgentState:
    instructions = []
    for d in state["diff"]:
        instructions.append(f"Update {d['category']} {d['key']} from {d['old']} to {d['new']}.")
    state["instructions"] = instructions
    return state

def run_agent_workflow():
    state = AgentState(plan_2025={}, plan_2026={}, diff=[], documents_to_update=[], instructions=[])
    state = load_plans(state)
    state = compute_diff(state)
    state = generate_instructions(state)
    logger.info(f"Agent generated instructions: {state['instructions']}")
    return state

if __name__ == "__main__":
    run_agent_workflow()
