"""Revision apparatus injection — change bars, record table, highlights.

Generates chat instructions for SuperDocs to add revision apparatus to a document.
All apparatus is injected via natural language chat instructions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .differ import DiffResult


@dataclass
class RevisionMetadata:
    revision_number: str
    date: str
    changes: list[str] = field(default_factory=list)
    affected_pages: list[str] = field(default_factory=list)
    highlights_summary: str = ""


# Maximum paragraphs per chat instruction (SuperDocs limit: 25 sections per op)
MAX_SECTIONS_PER_TURN = 25


def _build_change_bars_instruction(positions: list[int]) -> str:
    """Build a chat instruction to add change bars next to altered paragraphs."""
    if not positions:
        return ""
    pos_list = ", ".join(str(p) for p in positions)
    return (
        f"Add vertical revision change bars (solid black left border: "
        f"border-left: 4px solid #111; padding-left: 12px;) in the left margin next to "
        f"every altered paragraph. The changed paragraphs are at positions "
        f"[{pos_list}] (0-indexed). Only mark these specific altered paragraphs — "
        f"do not add bars anywhere else."
    )


def _build_record_table_instruction(
    metadata: RevisionMetadata, diff: DiffResult | None = None
) -> str:
    """Build a chat instruction to insert a revision-record table."""
    affected_str = ", ".join(metadata.affected_pages) if metadata.affected_pages else (
        f"Paragraphs {diff.changed_positions}"
        if diff and diff.changed_positions
        else "All / General"
    )
    if not metadata.changes:
        return (
            f"At the very top of the document (replacing any existing revision tables), "
            f"insert a 'Revision Record' table with these columns: "
            f"Revision Number, Date, Affected Pages/Sections, Summary of Change.\n"
            f"Row: | {metadata.revision_number} | {metadata.date} | None | No content changes |"
        )
    change_rows = "\n".join(
        f"| {metadata.revision_number} | {metadata.date} | {affected_str} | {c} |"
        for c in metadata.changes
    )
    return (
        f"At the very top of the document (replacing any existing revision tables), "
        f"insert a 'Revision Record' table with these columns: "
        f"Revision Number, Date, Affected Pages/Sections, Summary of Change.\n"
        f"Use the following rows:\n{change_rows}"
    )


def _build_lep_instruction(metadata: RevisionMetadata, diff: DiffResult) -> str:
    """Build a chat instruction for the List of Effective Pages (LEP)."""
    changed_pos = diff.changed_positions if diff else []
    changed_pos_str = ", ".join(str(p) for p in changed_pos) if changed_pos else "None"
    return (
        f"Insert a 'List of Effective Pages (LEP)' table immediately after the "
        f"Revision Record table with columns: Page/Section, Revision Number, Date, Status.\n"
        f"Use exact rows:\n"
        f"| Paragraphs [{changed_pos_str}] | {metadata.revision_number} | {metadata.date} | Revised |\n"
        f"| All other sections | Original | Original Issue | Original/Prior |"
    )


def _build_highlights_instruction(metadata: RevisionMetadata) -> str:
    """Build a chat instruction for highlights-of-change summary."""
    summary = metadata.highlights_summary or (
        "; ".join(metadata.changes) if metadata.changes else "Document updated per revision instructions."
    )
    return (
        f"Add a 'Highlights of Change' heading and summary paragraph after the List of Effective Pages table: "
        f"'Highlights of Change (Revision {metadata.revision_number}, {metadata.date}): {summary}'."
    )


@dataclass
class InstructionBatch:
    """A batch of chat instructions to send in a single turn."""

    instructions: list[str] = field(default_factory=list)

    @property
    def combined(self) -> str:
        """Combine all instructions into a single chat message."""
        parts = [i for i in self.instructions if i]
        return "\n\n".join(parts)


class RevisionApparatus:
    """Generates and injects revision apparatus via SuperDocs chat instructions.

    Combines all instructions (record table, LEP, highlights, change bars) into a
    single chat turn when ≤25 changed paragraphs, minimizing API calls.
    """

    def generate(self, diff: DiffResult, metadata: RevisionMetadata) -> list[InstructionBatch]:
        """Generate instruction batches from diff output and metadata.

        Returns a single batch when all instructions fit within the 25-section limit.
        """
        positions = diff.changed_positions
        batches: list[InstructionBatch] = []

        # Combine apparatus elements into one batch when possible
        instructions = [
            _build_record_table_instruction(metadata, diff),
            _build_lep_instruction(metadata, diff),
            _build_highlights_instruction(metadata),
        ]

        if positions:
            # Chunk change bars if >25 paragraphs
            for i in range(0, len(positions), MAX_SECTIONS_PER_TURN):
                chunk = positions[i : i + MAX_SECTIONS_PER_TURN]
                instructions.append(_build_change_bars_instruction(chunk))

        batches.append(InstructionBatch(instructions=instructions))
        return batches

    def generate_combined(self, diff: DiffResult, metadata: RevisionMetadata) -> list[str]:
        """Generate combined instruction strings, one per chat turn.

        Each string is a complete instruction to send via client.edit().
        """
        batches = self.generate(diff, metadata)
        return [b.combined for b in batches if b.combined]
