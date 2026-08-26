from __future__ import annotations
import re, time
from typing import TypedDict, Any
from app.services.vector_store import lexical_vector_search
try:
    from langgraph.graph import StateGraph, END
except ImportError:
    END = "__END__"
    class StateGraph:
        def __init__(self, _state_type): self.nodes={}; self.entry=None; self.edges={}; self.conditional=None
        def add_node(self,name,fn): self.nodes[name]=fn
        def set_entry_point(self,name): self.entry=name
        def add_edge(self,a,b): self.edges[a]=b
        def add_conditional_edges(self,a,fn,mapping): self.conditional=(a,fn,mapping)
        def compile(self):
            parent=self
            class Graph:
                def invoke(self,state):
                    cur=parent.entry
                    while cur != END:
                        state=parent.nodes[cur](state)
                        if parent.conditional and cur==parent.conditional[0]:
                            nxt=parent.conditional[1](state); cur=parent.conditional[2].get(nxt,nxt)
                        else: cur=parent.edges.get(cur,END)
                    return state
            return Graph()

class AgentState(TypedDict, total=False):
    run_id: str
    documents: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    facts: dict[str, dict[str, Any]]
    conflicts: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    updates: list[dict[str, Any]]
    deliverable: dict[str, Any]
    stage_log: list[dict[str, Any]]
    approved: dict[str, bool]
    stopped: bool
    error: str | None

STAGES = ["ingest", "extract", "reconcile", "compliance", "plan_update", "review", "commit"]

def _log(s: AgentState, stage: str, decision: str, detail: str) -> None:
    s.setdefault("stage_log", []).append({"stage": stage, "decision": decision, "detail": detail, "at": time.time()})

def ingest(s: AgentState) -> AgentState:
    docs = s.get("documents", [])
    _log(s, "ingest", "continue", f"Accepted {len(docs)} source documents.")
    return s

def extract(s: AgentState) -> AgentState:
    facts: dict[str, dict[str, Any]] = {}
    instruction_pattern = re.compile(r"\b(ignore|disregard|override|system prompt|assistant)\b", re.I)
    for doc in s.get("documents", []):
        name = doc["name"]
        text = doc.get("text", "")
        if instruction_pattern.search(text):
            facts.setdefault("__safety__", {})[name] = "Source contains instruction-like text; treated as data."
        for key, value in re.findall(r"(?im)^\s*([A-Za-z][A-Za-z0-9 _-]{1,50})\s*:\s*(.+?)\s*$", text):
            normalized = key.strip().lower().replace(" ", "_").replace("-", "_")
            facts.setdefault(normalized, {})[name] = value.strip()
    chunks=[{"source_name":d["name"],"text":d.get("text","")} for d in s.get("documents",[])]
    s["retrieval_hits"]=lexical_vector_search(chunks,"facts requirements conflicts",top_k=min(5,len(chunks)))
    s["facts"] = facts
    _log(s, "extract", "continue", f"Extracted {sum(len(v) for v in facts.values())} fact observations and ranked {len(s["retrieval_hits"])} source chunks.")
    return s

def reconcile(s: AgentState) -> AgentState:
    conflicts = []
    for key, sources in s.get("facts", {}).items():
        values = {str(v).strip() for v in sources.values()}
        if key != "__safety__" and len(values) > 1:
            conflicts.append({"id":f"conflict:{key}", "kind":"conflict", "field":key, "values":sources, "message":f"Sources disagree on {key}."})
    s["conflicts"] = conflicts
    decision = "escalate" if conflicts else "continue"
    _log(s, "reconcile", decision, f"Found {len(conflicts)} conflicting fields.")
    return s

def compliance(s: AgentState) -> AgentState:
    findings=[]
    for rule in s.get("rules", []):
        statement = rule.get("statement", "")
        lower = statement.lower()
        if "must contain" in lower:
            required = statement.split("must contain",1)[1].strip().strip(".:")
            corpus = "\n".join(d.get("text","") for d in s.get("documents",[])).lower()
            if required.lower() not in corpus:
                findings.append({"id":f"finding:{rule['id']}", "kind":"finding", "rule_id":rule["id"], "message":f"Required text not found: {required}"})
    s["findings"] = findings
    _log(s, "compliance", "escalate" if findings else "continue", f"Produced {len(findings)} findings.")
    return s

def plan_update(s: AgentState) -> AgentState:
    updates=[]
    if s.get("conflicts"):
        updates.append({"id":"update:conflicts", "kind":"update", "message":"Hold conflicting facts for human decision; do not silently choose a source."})
    if s.get("findings"):
        updates.append({"id":"update:findings", "kind":"update", "message":"Keep compliance gaps visible in the deliverable."})
    deliverable = {
        "title":"Grounded document register",
        "facts":s.get("facts",{}),
        "conflicts":s.get("conflicts",[]),
        "findings":s.get("findings",[]),
        "updates":updates,
        "source_count":len(s.get("documents",[])),
    }
    s["updates"] = updates; s["deliverable"] = deliverable
    _log(s, "plan_update", "continue", f"Prepared deliverable with {len(updates)} guarded updates.")
    return s

def review(s: AgentState) -> AgentState:
    pending = [*s.get("conflicts",[]), *s.get("findings",[])]
    approved = s.get("approved", {})
    missing = [item["id"] for item in pending if item["id"] not in approved]
    _log(s, "review", "wait" if missing else "continue", f"{len(missing)} decisions remain.")
    s["stopped"] = bool(missing)
    return s

def commit(s: AgentState) -> AgentState:
    approved=s.get("approved",{})
    if any(not v for v in approved.values()):
        s["deliverable"]["rejected_items"]=[k for k,v in approved.items() if not v]
    _log(s, "commit", "commit", "Committed only explicitly approved review items.")
    return s

def build_graph():
    graph=StateGraph(AgentState)
    graph.add_node("ingest", ingest); graph.add_node("extract", extract); graph.add_node("reconcile", reconcile)
    graph.add_node("compliance", compliance); graph.add_node("plan_update", plan_update); graph.add_node("review", review); graph.add_node("commit", commit)
    graph.set_entry_point("ingest")
    graph.add_edge("ingest","extract"); graph.add_edge("extract","reconcile"); graph.add_edge("reconcile","compliance"); graph.add_edge("compliance","plan_update"); graph.add_edge("plan_update","review")
    graph.add_conditional_edges("review", lambda s: "commit" if not s.get("stopped") else END, {"commit":"commit", END:END})
    graph.add_edge("commit", END)
    return graph.compile()

workflow = build_graph()
