from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field
from backend.core.workflow.stage import WorkflowState


class ScreenplayElement(BaseModel):
    element_type: str  # scene_heading, action, character, dialogue, parenthetical, transition, uncertain
    content: str
    element_index: int
    scene_number: Optional[int] = None
    character_name: Optional[str] = None
    confidence: float = 1.0


class ParsedScreenplay(BaseModel):
    title: Optional[str] = None
    elements: List[ScreenplayElement] = Field(default_factory=list)
    scene_count: int = 0
    character_list: List[str] = Field(default_factory=list)


class FormattingItem(BaseModel):
    """In-memory representation of one formatting suggestion."""
    element_index: int
    element_type: str
    scene_number: Optional[int] = None
    character_name: Optional[str] = None
    original_text: str
    formatted_text: str
    change_type: str  # capitalization, spacing, indentation, no_change, uncertain
    reason: str = ""
    diff_tokens: List[Dict[str, Any]] = Field(default_factory=list)
    content_drift: bool = False
    status: str = "pending"  # pending, approved, rejected
    reviewer_comment: Optional[str] = None
    confidence_score: float = 1.0


class ScreenplayWorkflowState(WorkflowState):
    document_text: str = ""
    parsed_screenplay: Optional[Dict[str, Any]] = None
    formatting_items: List[Dict[str, Any]] = Field(default_factory=list)
    diff_available: bool = False
    regeneration_count: int = 0


def as_state_dict(state: Any) -> Dict[str, Any]:
    """
    Normalise a workflow state to a plain dict.

    LangGraph passes the Pydantic ``state_schema`` instance into stage nodes,
    while unit tests and the regenerate endpoint pass plain dicts. Screenplay
    stages are dict-based, so they normalise their input through this helper.
    """
    if isinstance(state, dict):
        return state
    if hasattr(state, "model_dump"):
        return state.model_dump()
    return dict(state)
