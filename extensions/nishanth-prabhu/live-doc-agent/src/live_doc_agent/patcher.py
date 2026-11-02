"""Deterministic markdown parser, proposal validator, and surgical patch engine."""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from live_doc_agent.models import (
    Patch,
    PatchAmbiguityError,
    ProposalValidationError,
    ProposedChange,
    SectionNotFoundError,
    WikiDocument,
    WikiSection,
)


def _slugify(text: str) -> str:
    """Generate a clean slug identifier from heading text."""
    clean = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", clean)


def _make_whitespace_flexible_pattern(snippet: str) -> re.Pattern:
    """Create a regex pattern matching the snippet with flexible whitespace."""
    words = re.split(r"\s+", snippet.strip())
    pattern_str = r"\s+".join(re.escape(w) for w in words if w)
    return re.compile(pattern_str, re.IGNORECASE)


class DocumentPatcher:
    """Deterministic, defensive patcher and validator for markdown documents."""

    @staticmethod
    def parse_sections(markdown_text: str) -> List[WikiSection]:
        """Parse markdown text into structured WikiSection objects."""
        lines = markdown_text.splitlines(keepends=True)
        sections: List[WikiSection] = []

        if not lines:
            return sections

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        current_heading = "Preamble"
        current_id = "preamble"
        current_level = 0
        current_lines: List[str] = []
        start_line = 0

        for idx, line in enumerate(lines):
            match = heading_pattern.match(line.rstrip("\r\n"))
            if match:
                # Flush previous section if it has content or was a real heading
                if current_lines or current_level > 0:
                    raw_text = "".join(current_lines)
                    body_lines = current_lines[1:] if current_level > 0 else current_lines
                    body_text = "".join(body_lines).strip()
                    sections.append(
                        WikiSection(
                            section_id=current_id,
                            title=current_heading,
                            level=current_level,
                            content=body_text,
                            raw_text=raw_text,
                            start_line=start_line,
                            end_line=idx - 1 if idx > 0 else 0,
                        )
                    )

                # Start new section
                hashes, title = match.groups()
                current_level = len(hashes)
                current_heading = title.strip()
                current_id = _slugify(current_heading)
                current_lines = [line]
                start_line = idx
            else:
                current_lines.append(line)

        # Flush final section
        if current_lines:
            raw_text = "".join(current_lines)
            body_lines = current_lines[1:] if current_level > 0 else current_lines
            body_text = "".join(body_lines).strip()
            sections.append(
                WikiSection(
                    section_id=current_id,
                    title=current_heading,
                    level=current_level,
                    content=body_text,
                    raw_text=raw_text,
                    start_line=start_line,
                    end_line=len(lines) - 1,
                )
            )

        return sections

    @classmethod
    def find_section(
        cls, sections: List[WikiSection], target_name_or_id: str
    ) -> Optional[WikiSection]:
        """Find a section by exact match, slug match, or case-insensitive match."""
        target_norm = target_name_or_id.strip().lower()
        target_slug = _slugify(target_name_or_id)

        # 1. Exact match on section_id or title
        for sec in sections:
            if sec.section_id == target_slug or sec.title.strip() == target_name_or_id.strip():
                return sec

        # 2. Case-insensitive exact match on title
        for sec in sections:
            if sec.title.strip().lower() == target_norm:
                return sec

        return None

    @classmethod
    def validate_proposal(
        cls,
        document: WikiDocument,
        change: ProposedChange,
    ) -> None:
        """Validate that a proposed change is strictly safe and executable.

        Checks:
        1. target_section exists in document.
        2. old_snippet exists exactly once in target section.
        3. new_snippet is non-empty.
        4. confidence is within [0.0, 1.0].
        """
        # 1. Confidence check
        if not (0.0 <= change.confidence <= 1.0):
            raise ProposalValidationError(
                f"Invalid confidence score {change.confidence} for change '{change.change_id}' (must be 0.0 - 1.0)."
            )

        # 2. New snippet check
        if not change.new_snippet or not change.new_snippet.strip():
            raise ProposalValidationError(
                f"Proposed change '{change.change_id}' has an empty replacement snippet."
            )

        # 3. Section existence check
        sections = cls.parse_sections(document.content)
        target_sec = cls.find_section(sections, change.target_section)
        if not target_sec:
            raise SectionNotFoundError(
                f"Target section '{change.target_section}' not found in document '{document.title}'."
            )

        # 4. Old snippet occurrence check
        orig_snippet = change.old_snippet.strip()
        if not orig_snippet:
            raise ProposalValidationError(
                f"Proposed change '{change.change_id}' has an empty target snippet."
            )

        sec_raw = target_sec.raw_text
        count = sec_raw.count(orig_snippet)

        if count == 0:
            pattern = _make_whitespace_flexible_pattern(orig_snippet)
            matches = list(pattern.finditer(sec_raw))
            if len(matches) == 0:
                raise PatchAmbiguityError(
                    f"Target snippet '{orig_snippet}' not found in section '{target_sec.title}'."
                )
            elif len(matches) > 1:
                raise PatchAmbiguityError(
                    f"Ambiguous proposal: flexible pattern matches {len(matches)} times in section '{target_sec.title}'."
                )
        elif count > 1:
            raise PatchAmbiguityError(
                f"Ambiguous proposal: target snippet occurs {count} times in section '{target_sec.title}'."
            )

    @classmethod
    def apply_patch_to_content(
        cls,
        document_content: str,
        patch: Patch,
    ) -> str:
        """Surgically replace original_snippet with replacement_snippet inside target section.

        Refuses ambiguous patches (0 or >1 matches in target section).
        Preserves all untouched sections and formatting.
        """
        sections = cls.parse_sections(document_content)
        target_sec = cls.find_section(sections, patch.target_section)

        if not target_sec:
            raise SectionNotFoundError(
                f"Target section '{patch.target_section}' not found in document."
            )

        orig_snippet = patch.original_snippet.strip()
        repl_snippet = patch.replacement_snippet.strip()

        sec_raw = target_sec.raw_text
        count = sec_raw.count(orig_snippet)

        if count == 0:
            pattern = _make_whitespace_flexible_pattern(orig_snippet)
            matches = list(pattern.finditer(sec_raw))
            if len(matches) == 0:
                raise PatchAmbiguityError(
                    f"Original snippet '{orig_snippet}' not found in section '{target_sec.title}'."
                )
            elif len(matches) > 1:
                raise PatchAmbiguityError(
                    f"Ambiguous patch: flexible pattern matches {len(matches)} times in section '{target_sec.title}'."
                )
            new_sec_raw, sub_count = pattern.subn(repl_snippet, sec_raw, count=1)
            if sub_count != 1:
                raise PatchAmbiguityError(
                    f"Failed to cleanly substitute normalized snippet in section '{target_sec.title}'."
                )
        elif count > 1:
            raise PatchAmbiguityError(
                f"Ambiguous patch: snippet occurs {count} times in section '{target_sec.title}'."
            )
        else:
            new_sec_raw = sec_raw.replace(orig_snippet, repl_snippet, 1)

        # Rebuild full document using the updated section
        new_sections_raw: List[str] = []
        for sec in sections:
            if sec.section_id == target_sec.section_id and sec.start_line == target_sec.start_line:
                new_sections_raw.append(new_sec_raw)
            else:
                new_sections_raw.append(sec.raw_text)

        return "".join(new_sections_raw)

    @classmethod
    def get_untouched_sections(
        cls,
        before_content: str,
        after_content: str,
    ) -> List[Tuple[str, bool]]:
        """Compare sections before and after.

        Returns list of (section_title, is_unchanged).
        """
        before_secs = {s.title: s.content for s in cls.parse_sections(before_content)}
        after_secs = {s.title: s.content for s in cls.parse_sections(after_content)}

        results = []
        for title, before_body in before_secs.items():
            after_body = after_secs.get(title)
            is_unchanged = (after_body is not None) and (before_body == after_body)
            results.append((title, is_unchanged))

        return results

    @classmethod
    def verify_untouched_invariant(
        cls,
        before_content: str,
        after_content: str,
        expected_modified_sections: List[str],
    ) -> bool:
        """Verify that ONLY expected_modified_sections were modified and all others are unchanged."""
        expected_slugs = {_slugify(s) for s in expected_modified_sections}

        before_secs = {s.section_id: s.content for s in cls.parse_sections(before_content)}
        after_secs = {s.section_id: s.content for s in cls.parse_sections(after_content)}

        for sec_id, before_body in before_secs.items():
            if sec_id not in expected_slugs:
                after_body = after_secs.get(sec_id)
                if after_body != before_body:
                    return False
        return True
