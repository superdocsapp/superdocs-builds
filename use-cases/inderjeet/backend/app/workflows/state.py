from typing import TypedDict, Dict, Any, List, Optional

class DisruptionState(TypedDict):
    """
    State definition for the Disruption Re-Issue Engine workflow.
    Ensures clear variables exist to process travelers in isolated steps
    and recover successfully after unexpected halts.
    """
    batch_id: str
    disruption_event: Dict[str, Any]      # Extracted cancellation metadata
    travelers_list: List[Dict[str, Any]]   # Manifest database snapshots
    affected_traveler_ids: List[str]      # Travelers matching criteria
    current_traveler_index: int            # Currently processed passenger pointer (for resume)
    ops_summary: Dict[str, Any]           # Consolidated routing logs
    audit_logs: List[Dict[str, Any]]      # Cost, timing, and turn descriptions
    error: Optional[str]                  # Failure message if applicable
