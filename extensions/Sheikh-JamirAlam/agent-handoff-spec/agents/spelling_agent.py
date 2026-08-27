from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re

from schema import HandoffEnvelope, ReviewState, validate_envelope
from .llm import DiffModel


@dataclass
class DocumentState:
    document_id: str
    review_state: ReviewState
    sections: dict[str, str]
    chunks: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    raw_html: str | None = None


@dataclass(frozen=True)
class SpellingFixResult:
    document_id: str
    changed_sections: dict[str, tuple[str, str]]
    next_envelope: HandoffEnvelope


class SpellingFixAgent:
    agent_id = "spelling-agent"
    action_name = "fix spelling"

    def __init__(self, llm: DiffModel | None = None,
                 protected_section: str = "pricing_table") -> None:
        self.llm = llm
        self.protected_section = protected_section

    @staticmethod
    def _same_snapshot(left: str, right: str) -> bool:
        return re.sub(r"\s+", " ", left).strip() == re.sub(r"\s+", " ", right).strip()

    def process(
        self,
        raw_envelope: dict,
        document: DocumentState,
        replacements: dict[str, dict[str, str]],
    ) -> SpellingFixResult:
        envelope = validate_envelope(raw_envelope)
        self.validate_document(envelope, document)
        if envelope.assigned_to != self.agent_id:
            raise ValueError(
                f"envelope is assigned to {envelope.assigned_to}, not {self.agent_id}")
        for section in envelope.scope.target_sections:
            if section not in document.sections:
                raise ValueError(
                    f"target section is absent from document: {section}")
            if section in envelope.restrictions.forbidden_sections:
                raise ValueError(f"target section is forbidden: {section}")

        changed_sections: dict[str, tuple[str, str]] = {}
        if self.llm is not None:
            proposal = self.llm.propose(
                action=envelope.scope.action,
                sections={section: document.sections[section]
                          for section in envelope.scope.target_sections},
                restrictions=envelope.restrictions.forbidden_actions,
            )
            for change in proposal.changes:
                if change.section not in envelope.scope.target_sections:
                    raise ValueError(
                        f"LLM proposed change outside scope: {change.section}")
                if not self._same_snapshot(document.sections[change.section], change.before):
                    raise ValueError(
                        f"LLM before value is stale for section: {change.section}")
                before = document.sections[change.section]
                if change.after != before:
                    changed_sections[change.section] = (before, change.after)
        else:
            for section in envelope.scope.target_sections:
                before = document.sections[section]
                after = before
                for incorrect, corrected in replacements.get(section, {}).items():
                    after = after.replace(incorrect, corrected)
                if after != before:
                    changed_sections[section] = (before, after)
        for section in envelope.scope.target_sections:
            if section in changed_sections:
                continue

        untouched_sections = [
            section
            for section in document.sections
            if section not in envelope.scope.target_sections
        ]
        if self.protected_section not in untouched_sections:
            raise ValueError(
                f"document has no untouched {self.protected_section} for Agent B")

        next_envelope = HandoffEnvelope(
            document_id=document.document_id,
            assigned_to="math-check-agent",
            scope={
                "action": "verify totals",
                "target_sections": [self.protected_section],
            },
            restrictions={
                "forbidden_sections": [section for section in document.sections
                                       if section != self.protected_section],
                "forbidden_actions": ["edit spelling", "rewrite prose"],
            },
            review_state=(
                ReviewState.APPROVED
                if envelope.scope.action == "final spelling review"
                else ReviewState.PENDING_REVIEW
            ),
            issued_by=self.agent_id,
            issued_at=datetime.now(timezone.utc),
        )
        return SpellingFixResult(document.document_id, changed_sections, next_envelope)

    @staticmethod
    def validate_document(envelope: HandoffEnvelope, document: DocumentState) -> None:
        if envelope.document_id != document.document_id:
            raise ValueError(
                f"stale or mismatched document: expected {envelope.document_id}, "
                f"received {document.document_id}"
            )
        if document.review_state != envelope.review_state:
            raise ValueError(
                f"document review state is {document.review_state.value}, "
                f"envelope says {envelope.review_state.value}"
            )
