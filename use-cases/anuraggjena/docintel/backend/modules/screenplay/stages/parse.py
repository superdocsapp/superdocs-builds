from typing import Any, Dict, List, Optional
from backend.core.workflow.stage import StageNode
from backend.core.llm.provider import LLMProvider, LLMMessage
from backend.modules.screenplay.schemas import ParsedScreenplay, ScreenplayElement, as_state_dict
from backend.modules.screenplay.parser import ScreenplayParser
from backend.modules.screenplay.llm_config import get_screenplay_llm_provider, get_screenplay_llm_model
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ParseStage(StageNode):
    """
    Parse raw screenplay text into structured elements using deterministic parser.

    Uses ScreenplayParser for rule-based parsing (confidence >= 0.7).
    Falls back to LLM only for uncertain elements (confidence < 0.7).
    Clean screenplays produce ZERO LLM calls.
    """

    def __init__(self, llm_provider: Optional[LLMProvider] = None, model: Optional[str] = None):
        super().__init__(name="parse")
        self.llm = llm_provider if llm_provider is not None else get_screenplay_llm_provider()
        self.model = model if model is not None else get_screenplay_llm_model()
        self.parser = ScreenplayParser()

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        state = as_state_dict(state)
        document_text = state.get("document_text", "")
        if not document_text.strip():
            logger.warning("parse_stage_empty_document")
            return {
                "parsed_screenplay": ParsedScreenplay().model_dump(),
                "claims": []
            }

        try:
            # Step 1: Deterministic parse
            elements = self.parser.parse(document_text)

            # Step 2: Identify uncertain elements (confidence < 0.7)
            uncertain_elements = [e for e in elements if e.confidence < 0.7]

            # Step 3: AI fallback for uncertain elements
            if uncertain_elements:
                # Build index map for efficient lookup
                element_map = {e.element_index: i for i, e in enumerate(elements)}

                for uncertain_elem in uncertain_elements:
                    reclassified = await self._classify_with_llm(uncertain_elem, document_text)
                    if reclassified:
                        idx = element_map.get(uncertain_elem.element_index)
                        if idx is not None:
                            elements[idx] = reclassified

            # Step 4: Build ParsedScreenplay
            scene_count = max([e.scene_number for e in elements if e.scene_number], default=0)
            character_names = {e.character_name for e in elements if e.character_name}
            character_list = sorted(list(character_names))

            # Convert dataclass elements to Pydantic models
            pydantic_elements = [
                ScreenplayElement(
                    element_type=e.element_type,
                    content=e.content,
                    element_index=e.element_index,
                    scene_number=e.scene_number,
                    character_name=e.character_name,
                    confidence=e.confidence
                )
                for e in elements
            ]

            parsed_screenplay = ParsedScreenplay(
                title=None,
                elements=pydantic_elements,
                scene_count=scene_count,
                character_list=character_list
            )

            logger.info(
                "screenplay_parsed",
                element_count=len(elements),
                uncertain_count=len(uncertain_elements),
                scene_count=scene_count
            )

            # Convert elements to claims format for compatibility with review system
            claims = [
                {"content": f"[{e.element_type}] {e.content}", "tags": ["screenplay", e.element_type]}
                for e in pydantic_elements
            ]

            return {
                "parsed_screenplay": parsed_screenplay.model_dump(),
                "claims": claims
            }

        except Exception as e:
            logger.error("parse_stage_failed", error=str(e))
            return {
                "parsed_screenplay": ParsedScreenplay().model_dump(),
                "claims": [],
                "parse_error": str(e)
            }

    async def _classify_with_llm(self, element, full_text: str):
        """
        Use LLM to classify an uncertain element.

        Returns a reclassified ScreenplayElement or None if classification fails.
        """
        # Extract context around the uncertain element (3 lines before/after if possible)
        lines = full_text.splitlines()
        # Find the line in the text
        target_line = element.content
        context_lines = []

        for i, line in enumerate(lines):
            if line.strip() == target_line:
                start = max(0, i - 3)
                end = min(len(lines), i + 4)
                context_lines = lines[start:end]
                break

        if not context_lines:
            context_lines = [target_line]

        context = "\n".join(context_lines)

        messages = [
            LLMMessage(
                role="system",
                content=(
                    "You are a screenplay format expert. Classify the element type of a line in screenplay format. "
                    "Types: scene_heading, action, character, dialogue, parenthetical, transition."
                )
            ),
            LLMMessage(
                role="user",
                content=f"""Classify this screenplay line (marked with >>>):

Context:
{context}

Which element type is the line: "{target_line}"?

Return JSON:
{{
  "element_type": "action|character|dialogue|scene_heading|parenthetical|transition",
  "confidence": 0.0-1.0
}}"""
            )
        ]

        try:
            # Use a simple dict schema for the response
            from pydantic import BaseModel

            class ElementClassification(BaseModel):
                element_type: str
                confidence: float

            result = await self.llm.generate_structured(
                messages=messages,
                model=self.model,
                response_schema=ElementClassification
            )

            if isinstance(result, dict):
                element_type = result.get("element_type", "action")
                confidence = result.get("confidence", 0.5)
            else:
                element_type = result.element_type
                confidence = result.confidence

            # Return updated element (convert from dataclass)
            from backend.modules.screenplay.parser import ScreenplayElement as ParserElement
            return ParserElement(
                element_type=element_type,
                content=element.content,
                element_index=element.element_index,
                scene_number=element.scene_number,
                character_name=element.character_name,
                confidence=confidence
            )

        except Exception as e:
            logger.warning("llm_classification_failed", error=str(e), element=element.content[:50])
            return None
