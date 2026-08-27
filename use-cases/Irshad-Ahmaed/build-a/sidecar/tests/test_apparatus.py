"""Tests for the RevisionApparatus."""

from build_a.apparatus import RevisionApparatus, RevisionMetadata
from build_a.differ import ChangeType, DiffResult, ParagraphDiff


def _make_diff(count: int) -> DiffResult:
    """Create a DiffResult with N changed paragraphs."""
    changed = [
        ParagraphDiff(
            position=i,
            change_type=ChangeType.MODIFIED,
            old_text=f"Old paragraph {i}",
            new_text=f"New paragraph {i}",
        )
        for i in range(count)
    ]
    return DiffResult(changed=changed, total_paragraphs_old=count, total_paragraphs_new=count)


def test_generates_record_table() -> None:
    diff = _make_diff(1)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=["Updated section 3.1"],
        highlights_summary="Key safety update",
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    assert len(batches) >= 1
    combined = batches[0].combined
    assert "0042" in combined
    assert "2025-01-15" in combined
    assert "Updated section 3.1" in combined


def test_generates_change_bars_instruction() -> None:
    diff = _make_diff(3)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=["Change 1", "Change 2", "Change 3"],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    all_instructions = " ".join(b.combined for b in batches)
    assert "change bar" in all_instructions.lower() or "revision mark" in all_instructions.lower()


def test_chunks_when_exceeding_limit() -> None:
    diff = _make_diff(30)  # > 25 sections
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=[f"Change {i}" for i in range(30)],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    # Everything combined into 1 batch; change bars chunked within it
    assert len(batches) == 1
    combined = batches[0].combined
    # Should have 2 change bar instructions (25 + 5)
    assert combined.count("change bar") == 2


def test_no_changes_generates_only_record() -> None:
    diff = DiffResult(changed=[], total_paragraphs_old=5, total_paragraphs_new=5)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=["No content changes"],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    assert len(batches) == 1  # Only record + highlights, no change bars


def test_empty_changes_list() -> None:
    diff = DiffResult(changed=[], total_paragraphs_old=5, total_paragraphs_new=5)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=[],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    assert len(batches) == 1
    combined = batches[0].combined
    assert "0042" in combined
    assert "No content changes" in combined


def test_exact_25_sections_no_chunking() -> None:
    diff = _make_diff(25)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=[f"Change {i}" for i in range(25)],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    # Everything in 1 batch; 1 change bar instruction (25 sections fit in one)
    assert len(batches) == 1
    combined = batches[0].combined
    assert combined.count("change bar") == 1


def test_26_sections_chunks_into_two() -> None:
    diff = _make_diff(26)
    metadata = RevisionMetadata(
        revision_number="0042",
        date="2025-01-15",
        changes=[f"Change {i}" for i in range(26)],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    # Everything in 1 batch; 2 change bar instructions (25 + 1)
    assert len(batches) == 1
    combined = batches[0].combined
    assert combined.count("change bar") == 2


def test_generates_lep_instruction() -> None:
    diff = _make_diff(2)
    metadata = RevisionMetadata(
        revision_number="0043",
        date="2025-02-01",
        changes=["Section 4.1 updated", "Section 4.2 updated"],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    all_instructions = " ".join(b.combined for b in batches)
    assert "List of Effective Pages" in all_instructions or "LEP" in all_instructions
    assert "0043" in all_instructions
    assert "Revised" in all_instructions


def test_revision_record_includes_affected_pages() -> None:
    diff = _make_diff(1)
    metadata = RevisionMetadata(
        revision_number="0043",
        date="2025-02-01",
        changes=["Updated engine failure checklist"],
        affected_pages=["Section 4.2 (Page 7)"],
    )
    apparatus = RevisionApparatus()
    batches = apparatus.generate(diff, metadata)

    combined = batches[0].combined
    assert "Affected Pages/Sections" in combined
    assert "Section 4.2 (Page 7)" in combined
