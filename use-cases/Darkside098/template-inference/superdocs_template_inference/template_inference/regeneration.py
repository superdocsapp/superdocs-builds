"""Regeneration utilities for source-specific DOCX output from inferred templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt

from superdocs_template_inference.models import Document as NormalizedDocument, ParagraphBlock, TableBlock
from superdocs_template_inference.template_inference.result import (
    ConditionalRule,
    TemplateInferenceResult,
    TemplateSection,
)


@dataclass
class RegenerationResult:
    """Structured outcome for a DOCX regeneration operation."""

    output_path: str | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    included_sections: list[str] = field(default_factory=list)
    omitted_conditional_sections: list[str] = field(default_factory=list)
    substituted_variables: dict[str, str] = field(default_factory=dict)
    succeeded: bool = False


@dataclass
class FidelityComparisonResult:
    """Source-vs-regenerated DOCX fidelity comparison output."""

    overall_score: float
    text_similarity: float
    formatting_similarity: float
    structure_similarity: float
    discrepancies: list[str] = field(default_factory=list)
    supported_metrics: dict[str, float] = field(default_factory=dict)
    unsupported_fields: list[str] = field(default_factory=list)


class DocxFidelityComparator:
    """Compare a source document against its regenerated output with honest, conservative scoring."""

    def compare(self, source_document: NormalizedDocument, regenerated_document: NormalizedDocument) -> FidelityComparisonResult:
        """Score textual and formatting fidelity between the source and regenerated normalized documents."""
        source_blocks = [block for block in source_document.blocks if isinstance(block, ParagraphBlock)]
        regenerated_blocks = [block for block in regenerated_document.blocks if isinstance(block, ParagraphBlock)]

        text_similarity = self._text_similarity(source_blocks, regenerated_blocks)
        formatting_similarity = self._formatting_similarity(source_blocks, regenerated_blocks)
        structure_similarity = self._structure_similarity(source_document, regenerated_document)

        supported_metrics = {
            "text": text_similarity,
            "formatting": formatting_similarity,
            "structure": structure_similarity,
        }
        overall_score = 0.5 * text_similarity + 0.35 * formatting_similarity + 0.15 * structure_similarity

        discrepancies: list[str] = []
        if text_similarity < 1.0:
            discrepancies.append("Text content differs between source and regenerated output.")
        if formatting_similarity < 1.0:
            discrepancies.append("Detected formatting differences exist between source and regenerated output.")
        if structure_similarity < 1.0:
            discrepancies.append("Document structure differs between source and regenerated output.")

        unsupported_fields = [
            "run_level_font_variation",
            "embedded_object_geometry",
            "pixel-perfect_spacing",
        ]

        return FidelityComparisonResult(
            overall_score=max(0.0, min(1.0, overall_score)),
            text_similarity=max(0.0, min(1.0, text_similarity)),
            formatting_similarity=max(0.0, min(1.0, formatting_similarity)),
            structure_similarity=max(0.0, min(1.0, structure_similarity)),
            discrepancies=discrepancies,
            supported_metrics=supported_metrics,
            unsupported_fields=unsupported_fields,
        )

    def _text_similarity(self, source_blocks: list[ParagraphBlock], regenerated_blocks: list[ParagraphBlock]) -> float:
        """Measure token overlap between source and regenerated text content."""
        source_tokens = self._tokenize(" ".join(block.text for block in source_blocks if block.text))
        regenerated_tokens = self._tokenize(" ".join(block.text for block in regenerated_blocks if block.text))
        if not source_tokens and not regenerated_tokens:
            return 1.0
        if not source_tokens or not regenerated_tokens:
            return 0.0
        union = set(source_tokens) | set(regenerated_tokens)
        intersection = set(source_tokens) & set(regenerated_tokens)
        if not union:
            return 1.0
        return len(intersection) / len(union)

    def _formatting_similarity(self, source_blocks: list[ParagraphBlock], regenerated_blocks: list[ParagraphBlock]) -> float:
        """Compare conservative formatting signals that are actually preserved in the normalized model."""
        if not source_blocks and not regenerated_blocks:
            return 1.0
        if not source_blocks or not regenerated_blocks:
            return 0.0

        total = 0.0
        comparisons = 0
        for source_block, regenerated_block in zip(source_blocks, regenerated_blocks):
            comparisons += 1
            score = 0.0
            checks = 0
            for field_name in ("is_heading", "bold", "italic", "underline", "alignment"):
                source_value = getattr(source_block, field_name, None)
                regenerated_value = getattr(regenerated_block, field_name, None)
                if source_value is None and regenerated_value is None:
                    continue
                checks += 1
                if source_value == regenerated_value:
                    score += 1.0
            if source_block.style_name is not None or regenerated_block.style_name is not None:
                checks += 1
                if source_block.style_name == regenerated_block.style_name:
                    score += 1.0
            if source_block.font_size is not None or regenerated_block.font_size is not None:
                checks += 1
                if source_block.font_size is not None and regenerated_block.font_size is not None:
                    score += 1.0 if abs(source_block.font_size - regenerated_block.font_size) < 1.0 else 0.0
                elif source_block.font_size is None or regenerated_block.font_size is None:
                    score += 0.5
            if checks:
                total += score / checks
        if comparisons == 0:
            return 1.0
        return total / comparisons

    def _structure_similarity(self, source_document: NormalizedDocument, regenerated_document: NormalizedDocument) -> float:
        """Compare paragraph counts and block type patterns conservatively."""
        source_paragraphs = len([block for block in source_document.blocks if isinstance(block, ParagraphBlock)])
        regenerated_paragraphs = len([block for block in regenerated_document.blocks if isinstance(block, ParagraphBlock)])
        source_tables = len([block for block in source_document.blocks if isinstance(block, TableBlock)])
        regenerated_tables = len([block for block in regenerated_document.blocks if isinstance(block, TableBlock)])

        paragraph_ratio = 1.0 if source_paragraphs == 0 and regenerated_paragraphs == 0 else min(source_paragraphs, regenerated_paragraphs) / max(source_paragraphs, regenerated_paragraphs) if max(source_paragraphs, regenerated_paragraphs) else 1.0
        table_ratio = 1.0 if source_tables == 0 and regenerated_tables == 0 else min(source_tables, regenerated_tables) / max(source_tables, regenerated_tables) if max(source_tables, regenerated_tables) else 1.0
        return 0.5 * paragraph_ratio + 0.5 * table_ratio

    def _tokenize(self, text: str) -> list[str]:
        """Normalize token text for comparison."""
        return [token.lower() for token in re.findall(r"[A-Za-z0-9]+", text or "") if token.strip()]


class DocxRegenerator:
    """Generate a source-specific DOCX from an inferred template."""

    def regenerate(
        self,
        template: TemplateInferenceResult,
        values: dict[str, Any],
        *,
        source_document: NormalizedDocument | None = None,
        output_path: str | None = None,
    ) -> RegenerationResult:
        """Regenerate a DOCX using the inferred template and explicit values.

        The regeneration layer is intentionally conservative: if the inferred template
        does not contain enough safe content for a section, the section is skipped and
        a warning is recorded rather than inventing content.
        """
        result = RegenerationResult(output_path=output_path)

        if not template:
            result.errors.append("Template inference result is missing.")
            return result

        ordered_sections = sorted(template.sections, key=lambda section: section.order)
        if not ordered_sections:
            result.errors.append("Template has no sections to regenerate.")
            return result

        if output_path is None:
            output_path = str(Path.cwd() / "regenerated_document.docx")
            result.output_path = output_path

        doc = Document()
        included_sections: list[str] = []
        omitted_conditional_sections: list[str] = []

        for section in ordered_sections:
            if section.inferred_type == "CONDITIONAL" or section.presence_type == "conditional":
                should_include = self._should_include_conditional_section(section, template.conditional_rules, values)
                if not should_include:
                    omitted_conditional_sections.append(section.title_or_pattern)
                    continue

            try:
                rendered = self._render_section(section, values, source_document=source_document)
            except ValueError as exc:
                result.errors.append(f"Missing variable value for section '{section.title_or_pattern}': {exc}")
                continue

            if rendered is None:
                result.warnings.append(
                    f"Section '{section.title_or_pattern}' has insufficient information for safe regeneration; "
                    "the template lacks safe content and regeneration cannot proceed without inventing details."
                )
                continue

            if rendered:
                self._add_rendered_content(doc, rendered, source_document=source_document)
                included_sections.append(section.title_or_pattern)

        if result.warnings and not included_sections:
            result.errors.append("No safe content could be regenerated from the template.")
        if not result.errors and not included_sections:
            result.errors.append("No sections were regenerated from the template.")

        doc.save(output_path)
        result.included_sections = included_sections
        result.omitted_conditional_sections = omitted_conditional_sections

        if result.warnings and included_sections:
            result.errors.append("Regeneration completed with warnings; some content was skipped due to insufficient or unsafe template information.")

        result.succeeded = not result.errors

        if Path(output_path).exists() is False:
            result.errors.append(f"Regenerated DOCX could not be saved to '{output_path}'.")
            result.succeeded = False

        return result

    def _render_section(
        self,
        section: TemplateSection,
        values: dict[str, Any],
        *,
        source_document: NormalizedDocument | None,
    ) -> str | None:
        """Render a single section into source-safe text."""
        if section.content_representation:
            content = section.content_representation
            rendered = self._substitute_variables(content, values)
            if rendered is not None:
                return rendered

        fallback_text = self._extract_source_section_text(section, source_document)
        if fallback_text:
            return self._substitute_variables(fallback_text, values)

        return None

    def _safe_to_render(self, section: TemplateSection) -> bool:
        """Only render sections whose content can be represented safely."""
        if section.content_representation is None:
            return False
        if not str(section.content_representation).strip():
            return False
        return True

    def _extract_source_section_text(
        self,
        section: TemplateSection,
        source_document: NormalizedDocument | None,
    ) -> str | None:
        """Best-effort source extraction from a matching heading when available."""
        if source_document is None:
            return None

        target_title = self._normalize_section_label(section.title_or_pattern)
        if not target_title:
            return None

        collected: list[str] = []
        found_heading = False
        for block in source_document.blocks:
            if not isinstance(block, ParagraphBlock):
                continue
            paragraph_text = (block.text or "").strip()
            if not paragraph_text:
                continue

            if block.is_heading:
                normalized_heading = self._normalize_section_label(paragraph_text)
                if normalized_heading == target_title:
                    found_heading = True
                    continue
                if found_heading:
                    break
                continue

            if found_heading:
                if paragraph_text:
                    collected.append(paragraph_text)

        if collected:
            return "\n".join(collected)
        return None

    def _substitute_variables(self, text: str, values: dict[str, Any]) -> str | None:
        """Replace {{variable_name}} tokens with supplied values."""
        if text is None:
            return None

        token_pattern = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+)\s*\}\}")
        missing = []

        def replacer(match: re.Match[str]) -> str:
            variable_name = match.group(1)
            if variable_name not in values:
                missing.append(variable_name)
                return match.group(0)
            value = str(values[variable_name])
            return value

        substituted = token_pattern.sub(replacer, text)
        if missing:
            missing_names = ", ".join(sorted(set(missing)))
            raise ValueError(f"Missing variable value(s): {missing_names}")
        return substituted

    def _should_include_conditional_section(
        self,
        section: TemplateSection,
        rules: list[ConditionalRule],
        values: dict[str, Any],
    ) -> bool:
        """Evaluate a section's conditional rule against supplied values."""
        section_key = self._normalize_section_label(section.title_or_pattern)
        for rule in rules:
            if not rule.condition:
                continue
            rule_key = self._normalize_section_label(rule.target_section)
            if rule_key and rule_key != section_key:
                continue

            field = rule.condition.get("field")
            operator = rule.condition.get("operator", "==")
            expected = rule.condition.get("value")
            if field is None:
                continue

            actual = values.get(field)
            if field not in values:
                return False

            return self._evaluate_operator(actual, operator, expected)

        if section.conditional_info and section.conditional_info.get("condition"):
            condition = section.conditional_info["condition"]
            field = condition.get("field")
            operator = condition.get("operator", "==")
            expected = condition.get("value")
            if field is not None and field in values:
                return self._evaluate_operator(values.get(field), operator, expected)
            return False

        return False

    def _evaluate_operator(self, actual: Any, operator: str, expected: Any) -> bool:
        """Evaluate a simple condition against the provided value."""
        actual_text = str(actual).strip().lower()
        expected_text = str(expected).strip().lower()

        op = (operator or "").lower()
        if op in {"==", "=", "equals"}:
            return actual_text == expected_text
        if op in {"!=", "not_equals", "notequals"}:
            return actual_text != expected_text
        if op in {"contains", "in"}:
            return expected_text in actual_text
        if op in {"not_contains", "notin"}:
            return expected_text not in actual_text
        return False

    def _normalize_section_label(self, value: str | None) -> str:
        """Normalize section labels to their canonical slug form."""
        if not value:
            return ""
        normalized = value.strip().lower()
        normalized = normalized.replace("/", " ")
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized)
        normalized = normalized.strip("_")
        return normalized

    def _add_rendered_content(self, doc: Document, rendered: str, *, source_document: NormalizedDocument | None = None) -> None:
        """Add paragraph text to a docx document while preserving simple formatting where available."""
        for line in str(rendered).splitlines():
            clean_line = line.strip()
            if clean_line:
                paragraph = doc.add_paragraph(clean_line)
                self._apply_source_formatting(paragraph, clean_line, source_document=source_document)

    def _apply_source_formatting(self, paragraph, text: str, *, source_document: NormalizedDocument | None) -> None:
        """Style a regenerated paragraph to resemble the closest matching source paragraph when possible."""
        if source_document is None:
            return

        best_match = None
        best_score = -1.0
        for block in source_document.blocks:
            if not isinstance(block, ParagraphBlock):
                continue
            if not block.text:
                continue
            similarity = self._compare_text_similarity(block.text, text)
            if similarity > best_score:
                best_match = block
                best_score = similarity

        if best_match is None:
            return

        if best_match.style_name:
            try:
                paragraph.style = best_match.style_name
            except Exception:
                pass

        if best_match.alignment is not None:
            try:
                alignment_value = {
                    "left": 0,
                    "center": 1,
                    "right": 2,
                    "justify": 3,
                    "distributed": 4,
                }.get(best_match.alignment, 0)
                paragraph.alignment = alignment_value
            except Exception:
                pass

        if best_match.spacing_before is not None:
            try:
                paragraph.paragraph_format.space_before = Pt(best_match.spacing_before)
            except Exception:
                pass
        if best_match.spacing_after is not None:
            try:
                paragraph.paragraph_format.space_after = Pt(best_match.spacing_after)
            except Exception:
                pass

        if paragraph.runs:
            run = paragraph.runs[0]
            if best_match.bold is not None:
                run.bold = bool(best_match.bold)
            if best_match.italic is not None:
                run.italic = bool(best_match.italic)
            if best_match.underline is not None:
                run.font.underline = bool(best_match.underline)
            if best_match.font_name:
                run.font.name = best_match.font_name
            if best_match.font_size is not None:
                run.font.size = Pt(best_match.font_size)

    def _compare_text_similarity(self, source_text: str, rendered_text: str) -> float:
        """Simple token similarity used to match source paragraphs to regenerated output."""
        source_tokens = set(re.findall(r"[A-Za-z0-9]+", (source_text or "").lower()))
        rendered_tokens = set(re.findall(r"[A-Za-z0-9]+", (rendered_text or "").lower()))
        if not source_tokens and not rendered_tokens:
            return 1.0
        if not source_tokens or not rendered_tokens:
            return 0.0
        union = source_tokens | rendered_tokens
        overlap = source_tokens & rendered_tokens
        return len(overlap) / len(union) if union else 0.0


__all__ = ["DocxRegenerator", "RegenerationResult", "DocxFidelityComparator", "FidelityComparisonResult"]
