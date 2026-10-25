from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any


class ManualError(ValueError):
    pass


@dataclass(frozen=True)
class Diagram:
    diagram_id: str
    source_kind: str
    source_text: str
    nodes: dict[str, str]
    edges: tuple[tuple[str, str], ...]
    rendered_asset_hash: str


@dataclass
class Manual:
    manual_id: str
    title: str
    organization: str
    revision: int
    status: str
    effective_date: str
    sections: list[dict[str, Any]]
    diagrams: list[Diagram]
    revision_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = deepcopy(self.__dict__)
        result["diagrams"] = [diagram.__dict__ | {"edges": list(diagram.edges)} for diagram in self.diagrams]
        return result

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Manual":
        diagrams = [Diagram(**{**diagram, "edges": tuple(tuple(edge) for edge in diagram["edges"])}) for diagram in value["diagrams"]]
        return cls(**{**value, "diagrams": diagrams})

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


def parse_mermaid(diagram_id: str, source_text: str) -> Diagram:
    """Parse the constrained deterministic Mermaid subset used by the fixture."""
    if not source_text.startswith("flowchart "):
        raise ManualError("diagram source must start with flowchart")
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str]] = []
    for line in source_text.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        node_match = re.fullmatch(r"([A-Za-z0-9_-]+)\[\"([^\"]+)\"\]", stripped)
        edge_match = re.fullmatch(r"([A-Za-z0-9_-]+)\s+-->\s+([A-Za-z0-9_-]+)", stripped)
        if node_match:
            node_id, label = node_match.groups()
            if " | " not in label:
                raise ManualError(f"diagram node {node_id} must include step_id | label")
            step_id, text = label.split(" | ", 1)
            nodes[step_id] = text
        elif edge_match:
            edges.append(edge_match.groups())
        else:
            raise ManualError(f"unsupported Mermaid line: {stripped}")
    if not nodes:
        raise ManualError("diagram must contain nodes")
    if any(source not in nodes or target not in nodes for source, target in edges):
        raise ManualError(f"diagram {diagram_id} has an edge to an unknown node")
    source_hash = hashlib.sha256(source_text.encode()).hexdigest()
    return Diagram(diagram_id, "mermaid", source_text, nodes, tuple(edges), source_hash)


def validate_manual(manual: Manual) -> None:
    if manual.revision < 1:
        raise ManualError("revision must be positive")
    section_ids = {section["section_id"] for section in manual.sections}
    diagram_ids = {diagram.diagram_id for diagram in manual.diagrams}
    if len(section_ids) != len(manual.sections) or len(diagram_ids) != len(manual.diagrams):
        raise ManualError("section and diagram IDs must be unique")
    for diagram in manual.diagrams:
        for source, target in diagram.edges:
            if source not in diagram.nodes or target not in diagram.nodes:
                raise ManualError(f"diagram {diagram.diagram_id} has an edge to an unknown node")
    for section in manual.sections:
        diagram_id = section.get("diagram_ref")
        if diagram_id and diagram_id not in diagram_ids:
            raise ManualError(f"section {section['section_id']} references unknown diagram")
