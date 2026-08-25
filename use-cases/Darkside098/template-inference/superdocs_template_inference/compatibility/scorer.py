"""Pairwise compatibility scoring using observable DocumentProfile signals."""

from __future__ import annotations

from superdocs_template_inference.compatibility.config import CompatibilityConfig
from superdocs_template_inference.compatibility.result import CompatibilityEvidence, CompatibilityResult
from superdocs_template_inference.compatibility.signals import (
    block_sequence_similarity,
    block_structure_similarity,
    document_length_similarity,
    heading_distribution_similarity,
    heading_vocabulary_similarity,
    section_count_similarity,
    section_structure_similarity,
    table_structure_similarity,
    vocabulary_overlap,
)
from superdocs_template_inference.models import DocumentProfile


class CompatibilityScorer:
    """Compare two DocumentProfile instances with determinism and symmetry."""

    def __init__(self, config: CompatibilityConfig | None = None):
        self.config = config or CompatibilityConfig()

    def _signal_order(self) -> list[tuple[str, str]]:
        """Return the deterministic evidence order for all compatibility signals."""
        return [
            ("block_structure_similarity", "block_structure"),
            ("block_sequence_similarity", "block_sequence"),
            ("heading_distribution_similarity", "heading_distribution"),
            ("section_count_similarity", "section_count"),
            ("section_structure_similarity", "section_structure"),
            ("vocabulary_overlap", "content"),
            ("heading_vocabulary_similarity", "heading_vocabulary"),
            ("table_structure_similarity", "table_structure"),
            ("document_length_similarity", "document_length"),
        ]

    def _calculate_profile_completeness(self, profile: DocumentProfile) -> float:
        """Measure completeness of a profile in a symmetric, deterministic manner."""
        completeness = 0.0
        if profile.structural.total_blocks > 0:
            completeness += 0.2
        if profile.structural.heading_count > 0:
            completeness += 0.2
        if len(profile.sections) > 0:
            completeness += 0.2
        if profile.content.unique_words_count > 0:
            completeness += 0.2
        if profile.structural.table_count > 0 or bool(profile.structural.table_dimensions):
            completeness += 0.2

        return max(0.0, min(1.0, completeness))

    def _calculate_confidence(self, profile_a: DocumentProfile, profile_b: DocumentProfile, signal_scores: dict[str, float]) -> float:
        """A symmetric confidence measure derived from both profiles and signal agreement."""
        values = list(signal_scores.values())
        if not values:
            return 0.0

        mean = sum(values) / len(values)
        variance = sum((value - mean) ** 2 for value in values) / len(values)
        signal_agreement = max(0.0, 1.0 - (variance / 0.25))

        completeness_a = self._calculate_profile_completeness(profile_a)
        completeness_b = self._calculate_profile_completeness(profile_b)
        profile_completeness = (completeness_a + completeness_b) / 2.0

        confidence = 0.6 * signal_agreement + 0.4 * profile_completeness
        return max(0.0, min(1.0, confidence))

    def compare(self, profile_a: DocumentProfile, profile_b: DocumentProfile) -> CompatibilityResult:
        """Compare two DocumentProfile objects and return a deterministic structured result."""
        signal_functions = {
            "block_structure_similarity": block_structure_similarity,
            "block_sequence_similarity": block_sequence_similarity,
            "heading_distribution_similarity": heading_distribution_similarity,
            "section_count_similarity": section_count_similarity,
            "section_structure_similarity": section_structure_similarity,
            "vocabulary_overlap": vocabulary_overlap,
            "heading_vocabulary_similarity": heading_vocabulary_similarity,
            "table_structure_similarity": table_structure_similarity,
            "document_length_similarity": document_length_similarity,
        }

        signal_scores: dict[str, float] = {}
        for signal_name, _ in self._signal_order():
            value = signal_functions[signal_name](profile_a, profile_b)
            signal_scores[signal_name] = value

        score = (
            self.config.weight_block_structure * signal_scores["block_structure_similarity"]
            + self.config.weight_block_sequence * signal_scores["block_sequence_similarity"]
            + self.config.weight_heading_distribution * signal_scores["heading_distribution_similarity"]
            + self.config.weight_section_count * signal_scores["section_count_similarity"]
            + self.config.weight_section_structure * signal_scores["section_structure_similarity"]
            + self.config.weight_vocabulary_overlap * signal_scores["vocabulary_overlap"]
            + self.config.weight_heading_vocabulary * signal_scores["heading_vocabulary_similarity"]
            + self.config.weight_table_structure * signal_scores["table_structure_similarity"]
            + self.config.weight_document_length * signal_scores["document_length_similarity"]
        )
        score = max(0.0, min(1.0, score))

        confidence = self._calculate_confidence(profile_a, profile_b, signal_scores)
        compatible = score >= self.config.compatibility_threshold

        evidence: list[CompatibilityEvidence] = []
        for signal_name, evidence_type in self._signal_order():
            value = signal_scores[signal_name]
            details = {
                "profile_a_id": profile_a.document_id,
                "profile_b_id": profile_b.document_id,
                "profile_a_filename": profile_a.filename,
                "profile_b_filename": profile_b.filename,
                "value": value,
            }

            if signal_name == "block_structure_similarity":
                details.update({
                    "profile_a_total_blocks": profile_a.structural.total_blocks,
                    "profile_b_total_blocks": profile_b.structural.total_blocks,
                    "profile_a_paragraph_count": profile_a.structural.paragraph_count,
                    "profile_b_paragraph_count": profile_b.structural.paragraph_count,
                })
            elif signal_name == "block_sequence_similarity":
                details.update({
                    "profile_a_sequence": profile_a.structural.block_type_sequence,
                    "profile_b_sequence": profile_b.structural.block_type_sequence,
                })
            elif signal_name == "heading_distribution_similarity":
                details.update({
                    "profile_a_heading_levels": profile_a.structural.heading_levels,
                    "profile_b_heading_levels": profile_b.structural.heading_levels,
                })
            elif signal_name == "section_count_similarity":
                details.update({
                    "profile_a_section_count": len(profile_a.sections),
                    "profile_b_section_count": len(profile_b.sections),
                })
            elif signal_name == "section_structure_similarity":
                details.update({
                    "profile_a_section_heading_levels": [section.heading_level for section in profile_a.sections],
                    "profile_b_section_heading_levels": [section.heading_level for section in profile_b.sections],
                })
            elif signal_name == "vocabulary_overlap":
                details.update({
                    "profile_a_vocabulary": profile_a.content.vocabulary,
                    "profile_b_vocabulary": profile_b.content.vocabulary,
                })
            elif signal_name == "heading_vocabulary_similarity":
                details.update({
                    "profile_a_heading_texts": profile_a.content.heading_texts,
                    "profile_b_heading_texts": profile_b.content.heading_texts,
                })
            elif signal_name == "table_structure_similarity":
                details.update({
                    "profile_a_table_count": profile_a.structural.table_count,
                    "profile_b_table_count": profile_b.structural.table_count,
                    "profile_a_table_dimensions": profile_a.structural.table_dimensions,
                    "profile_b_table_dimensions": profile_b.structural.table_dimensions,
                })
            elif signal_name == "document_length_similarity":
                details.update({
                    "profile_a_total_text_length": profile_a.content.total_text_length,
                    "profile_b_total_text_length": profile_b.content.total_text_length,
                })

            evidence.append(
                CompatibilityEvidence(
                    type=evidence_type,
                    signal_name=signal_name,
                    value=value,
                    description=f"{signal_name} calculated from both profiles.",
                    details=details,
                )
            )

        return CompatibilityResult(
            profile_a_id=profile_a.document_id,
            profile_b_id=profile_b.document_id,
            profile_a_filename=profile_a.filename,
            profile_b_filename=profile_b.filename,
            score=score,
            confidence=confidence,
            compatible=compatible,
            threshold=self.config.compatibility_threshold,
            evidence=evidence,
            signal_scores=signal_scores,
            comparison_version="1.0",
        )
