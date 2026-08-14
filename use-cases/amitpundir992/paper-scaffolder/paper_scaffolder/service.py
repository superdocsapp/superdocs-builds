"""Application service for the framework-independent vertical slice."""

from __future__ import annotations

from dataclasses import replace

from .grounding import ExactEvidenceGroundingGuard, evidence_for
from .models import (
    ManuscriptSection,
    ManuscriptSkeleton,
    PaperInputs,
    SectionGenerationResult,
    SectionStatus,
)
from .section_writer import ExtractiveSectionWriter, SectionWriter
from .skeleton import SkeletonGenerator
from .template_parser import JournalTemplateParser
from .validation import validate_inputs


class SectionNotFoundError(ValueError):
    """Raised when a requested section is not part of the supplied template."""


class ManuscriptService:
    """Coordinate validation, template parsing, scaffolding, and grounded writing."""

    def __init__(
        self,
        *,
        writer: SectionWriter | None = None,
        template_parser: JournalTemplateParser | None = None,
    ) -> None:
        self._writer = writer or ExtractiveSectionWriter()
        self._template_parser = template_parser or JournalTemplateParser()
        self._skeleton_generator = SkeletonGenerator()
        self._grounding_guard = ExactEvidenceGroundingGuard()

    def create_scaffold(self, inputs: PaperInputs) -> ManuscriptSkeleton:
        validated = validate_inputs(inputs)
        titles = self._template_parser.extract_sections(validated.journal_template)
        return self._skeleton_generator.create(validated, titles)

    def generate_section(
        self, inputs: PaperInputs, section_id: str
    ) -> SectionGenerationResult:
        validated = validate_inputs(inputs)
        skeleton = self.create_scaffold(validated)
        section = self._find_section(skeleton, section_id)

        if section.status is SectionStatus.INSUFFICIENT_INFORMATION:
            return SectionGenerationResult(skeleton.manuscript_id, section)

        evidence = evidence_for(section.available_sources, validated)
        draft = self._writer.generate(section.title, evidence).strip()
        if not self._grounding_guard.accepts(draft, evidence):
            rejected = replace(
                section,
                status=SectionStatus.INSUFFICIENT_INFORMATION,
                content="",
                reason=(
                    "Generated content was rejected because it was not an exact, "
                    "verifiable restatement of the supplied information."
                ),
            )
            return SectionGenerationResult(skeleton.manuscript_id, rejected)

        generated = replace(
            section,
            status=SectionStatus.GENERATED,
            content=draft,
            reason="Generated only from the listed researcher-supplied source.",
        )
        return SectionGenerationResult(skeleton.manuscript_id, generated)

    @staticmethod
    def _find_section(
        skeleton: ManuscriptSkeleton, section_id: str
    ) -> ManuscriptSection:
        for section in skeleton.sections:
            if section.section_id == section_id:
                return section
        raise SectionNotFoundError(
            f"Section '{section_id}' is not part of the supplied journal structure."
        )
