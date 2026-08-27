import os
import json
from typing import Protocol

from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field


class ProposedChange(BaseModel):
    section: str = Field(min_length=1)
    before: str
    after: str


class DiffProposal(BaseModel):
    changes: list[ProposedChange] = Field(default_factory=list)


class DiffModel(Protocol):
    def propose(self, *, action: str, sections: dict[str, str], restrictions: list[str]) -> DiffProposal:
        """Return structured before/after changes without mutating the input"""


class GeminiDiffAdapter:
    def __init__(self, model_name: str | None = None) -> None:
        model_name = model_name or os.getenv(
            "GEMINI_MODEL", "gemini-3.5-flash-lite")
        self._model = ChatGoogleGenerativeAI(
            model=model_name,
            # temperature=0,
        ).with_structured_output(DiffProposal, method="json_mode")

    def propose(self, *, action: str, sections: dict[str, str], restrictions: list[str]) -> DiffProposal:
        prompt = (
            "You are a document editing sub-agent.\n"
            f"Task: {action}\n"
            f"Forbidden actions: {restrictions or ['none']}\n"
            "Return only genuine, minimal before/after changes. Preserve all text that does not require changing. Do not invent sections or document content.\n"
            "The `before` field is an exact snapshot, not an editable field: copy it "
            "character-for-character from the supplied section value. Put only the "
            "requested corrections in `after`. Do not fix spelling, punctuation, "
            "spacing, or formatting in `before`.\n"
            "Sections are provided as JSON so that newlines and punctuation are literal:\n"
            f"{json.dumps(sections, ensure_ascii=False)}"
        )
        if os.getenv("SUPERDOCS_VERBOSE", "").lower() in {"1", "true", "yes", "on"}:
            print(f"[Gemini] action={action!r} sections={list(sections)}")
            for section, value in sections.items():
                print(f"[Gemini] input section={section!r} value={value!r}")
        result = self._model.invoke(prompt)
        if os.getenv("SUPERDOCS_VERBOSE", "").lower() in {"1", "true", "yes", "on"}:
            print(f"[Gemini] result changes={len(result.changes)}")
            for change in result.changes:
                print(f"[Gemini] result section={change.section!r}")
                print(f"[Gemini] result before={change.before!r}")
                print(f"[Gemini] result after={change.after!r}")
        return result
