from review_fsm.transitions import diagram_edges


def mermaid_state_diagram() -> str:
    lines = ["stateDiagram-v2"]
    for source, event, target in diagram_edges():
        lines.append(f"    {source.value} --> {target.value}: {event.value}")
    lines.append("    note right of RECOVERY_REQUIRED: Reconcile provider and durable store")
    return "\n".join(lines)
