"""Typed, deterministic safety flow graph and Mermaid renderer."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib, json, re

@dataclass(frozen=True)
class FlowNode:
    id: str; kind: str; label: str; evidence_ids: tuple[str, ...] = ()

@dataclass(frozen=True)
class FlowEdge:
    source: str; target: str; label: str = ""

@dataclass(frozen=True)
class FlowGraph:
    nodes: tuple[FlowNode, ...]; edges: tuple[FlowEdge, ...]

    def validate(self) -> None:
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes) or not {"START", "COMPLETE"} <= ids: raise ValueError("invalid flow node identity")
        if any(e.source not in ids or e.target not in ids for e in self.edges): raise ValueError("flow edge references unknown node")
        if any(n.kind == "decision" and (len([e for e in self.edges if e.source == n.id]) != 2 or {e.label for e in self.edges if e.source == n.id} != {"yes", "no"}) for n in self.nodes): raise ValueError("decision must have explicit yes/no branches")
        if any(n.kind not in {"start","complete"} and not n.evidence_ids for n in self.nodes): raise ValueError("operational flow nodes require evidence IDs")

    def mermaid(self) -> str:
        self.validate(); lines=["flowchart TD"]
        for n in self.nodes:
            shape = f"(({n.label}))" if n.kind in {"start","complete"} else (f"{{{n.label}}}" if n.kind == "decision" else f"[{n.label}]")
            lines.append(f"  {n.id}{shape}")
        for e in self.edges: lines.append(f"  {e.source} -->|{e.label}| {e.target}")
        return "\n".join(lines) + "\n"

    def digest(self) -> str: return hashlib.sha256(self.mermaid().encode()).hexdigest()

    def validate_mermaid(self) -> None:
        source = self.mermaid()
        if "flowchart TD" not in source or any(x not in source for x in ("-->", "yes", "no")): raise ValueError("invalid Mermaid source")

def sanitize_mermaid(source: str) -> str:
    if re.search(r"https?://|<\s*(script|iframe)|javascript:", source, re.I): raise ValueError("unsafe diagram content")
    return re.sub(r"[^\x09\x0A\x0D\x20-\x7E]", "", source)

def hero_flow() -> FlowGraph:
    graph = FlowGraph((FlowNode("START","start","START"), FlowNode("ISOLATED","decision","Energy isolated?",("SAFE-001",)), FlowNode("STOP","stop","STOP",("SAFE-001",)), FlowNode("CLEAR","step","Clear obstruction",("STEP-003",)), FlowNode("INTERLOCK","decision","Guard and interlock verified?",("RESTART-001",)), FlowNode("COMPLETE","complete","COMPLETE",("RESTART-001",))), (FlowEdge("START","ISOLATED"),FlowEdge("ISOLATED","CLEAR","yes"),FlowEdge("ISOLATED","STOP","no"),FlowEdge("CLEAR","INTERLOCK"),FlowEdge("INTERLOCK","COMPLETE","yes"),FlowEdge("INTERLOCK","STOP","no")))
    graph.validate(); return graph

def reject_unsupported_numbers(label: str) -> None:
    if re.search(r"\b(?:\d+(?:\.\d+)?\s*(?:seconds?|minutes?|psi|bar|rpm|°C|mm))\b", label, re.I):
        raise ValueError("unsupported operational number in flow graph")
