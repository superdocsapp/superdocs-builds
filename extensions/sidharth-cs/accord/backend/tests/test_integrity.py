"""Locks in the two-signal structural-integrity check — the load-bearing
safety net against the documented SuperDocs silent-content-loss risk."""

from app.superdocs.integrity import check_integrity

BEFORE = (
    "<h1>Statement of Work</h1><h2>Parties</h2><p>Northwind and Meridian.</p>"
    "<h2>Scope</h2><p>Warehouse automation consulting.</p>"
    "<h2>Commercials</h2><p>Fees: USD 48,000. Start date: 3 September 2026.</p>"
)


def test_clean_correction_passes():
    after = BEFORE.replace("3 September 2026", "15 September 2026")
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "update", "chunk_id": "c1"}],
        classification="correction",
    )
    assert result.passed


def test_clean_addition_passes():
    after = BEFORE + "<h2>Signatures</h2><p>Signed by both parties.</p>"
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "create", "chunk_id": "c1"}],
        classification="addition",
    )
    assert result.passed


def test_addition_with_only_deletes_is_flagged():
    after = BEFORE.replace("<h2>Scope</h2><p>Warehouse automation consulting.</p>", "")
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "delete", "chunk_id": "c1"}],
        classification="addition",
    )
    assert not result.passed
    assert "delete" in result.reason


def test_correction_touching_many_chunks_is_flagged():
    result = check_integrity(
        html_before=BEFORE,
        html_after=BEFORE,
        changes=[{"operation": "update", "chunk_id": f"c{i}"} for i in range(5)],
        classification="correction",
    )
    assert not result.passed
    assert "5 chunks" in result.reason


def test_section_count_drop_is_flagged_even_with_proportionate_diff():
    # Mirrors the documented failure mode: SuperDocs' own diff can look
    # small while the reassembled document actually lost a whole section.
    after = BEFORE.replace("<h2>Scope</h2><p>Warehouse automation consulting.</p>", "")
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "update", "chunk_id": "c1"}],  # looks proportionate
        classification="addition",
    )
    assert not result.passed
    assert "section count" in result.reason


def test_large_text_shrink_is_flagged_independent_of_section_count():
    # Same headings survive, but the content under them is gutted — isolates
    # Signal B's text-length check from its section-count check.
    after = (
        "<h1>Statement of Work</h1><h2>Parties</h2><p>-</p>"
        "<h2>Scope</h2><p>-</p><h2>Commercials</h2><p>-</p>"
    )
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "update", "chunk_id": "c1"}],
        classification="addition",
    )
    assert not result.passed
    assert "shrank" in result.reason


def test_removal_expected_bypasses_the_structural_signals():
    after = "<h1>Statement of Work</h1>"
    result = check_integrity(
        html_before=BEFORE,
        html_after=after,
        changes=[{"operation": "delete", "chunk_id": "c1"}],
        classification="addition",
        removal_expected=True,
    )
    assert result.passed


# --- auto-applied edits (the path that skipped the proposal gate) ----------
#
# SuperDocs sometimes applies an edit itself and reports "completed" instead
# of offering it for approval. That path ran only check_integrity, never
# validate_proposal, so placeholders and invented tables went straight into
# the document unchecked. Every case below is taken from one real exported
# .docx produced by a live meeting.

from app.superdocs.integrity import structural_defect

_BEFORE = "<h2>Assumptions</h2><table><tr><td>Client</td><td>Acme</td></tr></table>"


def test_placeholder_written_by_an_auto_applied_edit_is_rejected():
    after = _BEFORE + "<p>Please fill: Project assumptions and dependencies</p>"
    assert "placeholder" in (structural_defect(_BEFORE, after) or "")


def test_second_table_invented_by_an_auto_applied_edit_is_rejected():
    after = _BEFORE + "<table><tr><td><strong>Status</strong></td><td>x</td></tr></table>"
    assert "gained a table" in (structural_defect(_BEFORE, after) or "")


def test_rephrased_duplicate_paragraphs_are_rejected():
    # Verbatim matching missed these: a retry rephrases rather than repeats,
    # and the real export carried four variants of this one sentence.
    after = _BEFORE + (
        "<p>We expect weekly progress updates and we will see you next time. "
        "Please review each milestone before moving forward.</p>"
        "<p>We expect weekly progress updates and look forward to seeing you next time. "
        "Please review each project milestone before moving forward.</p>"
    )
    assert "restates existing content" in (structural_defect(_BEFORE, after) or "")


def test_a_clean_edit_passes():
    after = _BEFORE + "<p>The total project budget is $45,000 for this engagement.</p>"
    assert structural_defect(_BEFORE, after) is None


def test_restatement_inside_one_paragraph_is_caught():
    """The restatement usually lands in the SAME paragraph as the original,
    which block-level comparison never sees. From a real clean run's export:
    Scope of Work said the same thing twice in one <p>."""
    from app.superdocs.integrity import _near_duplicate_block

    html = (
        "<p>We will develop a modern, responsive website that allows customers to "
        "browse products, add items to a cart, and complete payments online. "
        "We need a modern responsive website where customers can browse products, "
        "add items to a cart, and complete payments online.</p>"
    )
    assert _near_duplicate_block(html) is not None


def test_reworded_repeat_across_sections_is_caught_on_the_approval_path():
    """check_integrity only matched VERBATIM repeats, so the ordinary
    approval path was blind to rewording — the Assumptions paragraph was
    exported again under Next Steps."""
    from app.superdocs.integrity import check_integrity

    before = "<h2>Assumptions</h2><p>Existing.</p>"
    after = (
        "<h2>Assumptions</h2><p>We'll provide the product images, descriptions, "
        "pricing, branding assets, and access to our existing domain.</p>"
        "<h2>Next Steps</h2><p>We will provide the product images, descriptions, "
        "pricing, and branding assets. Additionally, we will grant access to our "
        "existing domain to facilitate the development process.</p>"
    )
    result = check_integrity(
        html_before=before, html_after=after, changes=[], classification="addition"
    )
    assert not result.passed
    assert "restates" in (result.reason or "")


def test_distinct_sections_are_not_flagged():
    from app.superdocs.integrity import check_integrity

    before = "<h2>Deliverables</h2><p>Existing.</p>"
    after = (
        "<h2>Deliverables</h2><p>The deliverables include the website, payment "
        "integration, mobile responsive design, and basic analytics.</p>"
        "<h2>Timeline</h2><p>The project is scheduled to start on September 15th, "
        "and the final website delivery is due by October 30th.</p>"
    )
    assert check_integrity(
        html_before=before, html_after=after, changes=[], classification="addition"
    ).passed
