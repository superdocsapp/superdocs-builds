from core.models import EntryStatus
from core.parser import parse_objection_notes


def test_scenario_a_mixed_formats_are_preserved():
    lines = [
        "Random sales call notes",
        "- It's too expensive",
        (
            "resp: Start with a small pilot "
            "rather than a full rollout."
        ),
        "* SECURITY???",
        "We encrypt data in transit and at rest.",
        '"We already use another vendor"',
        (
            "-> Migration can be phased alongside "
            "the existing workflow."
        ),
        "• Implementation looks complicated",
        "what about support?",
        (
            "A: Support is available during onboarding."
        ),
        "- Our team is too small",
        (
            "Response: Start with a limited team "
            "and expand later."
        ),
    ]

    result = parse_objection_notes(
        lines
    )

    assert result.objection_count == 6
    assert result.complete_count == 5
    assert (
        result.missing_response_count
        == 1
    )

    assert [
        entry.objection
        for entry in result.entries
    ] == [
        "It's too expensive",
        "SECURITY???",
        "We already use another vendor",
        "Implementation looks complicated",
        "what about support?",
        "Our team is too small",
    ]

    missing = result.entries[3]

    assert (
        missing.status
        == EntryStatus.MISSING_RESPONSE
    )

    assert missing.response is None


def test_scenario_b_different_syntax():
    lines = [
        "Q4 notes - messy version",
        "OBJ: Budget is frozen",
        (
            "ANS: Revisit the conversation "
            "in Q4."
        ),
        '"Already using Competitor X"',
        "→ Migration can be phased.",
        "- Worried about onboarding",
        "* Need training?",
        (
            "answer: Training is included "
            "during onboarding."
        ),
    ]

    result = parse_objection_notes(
        lines
    )

    assert result.objection_count == 4
    assert result.complete_count == 3
    assert (
        result.missing_response_count
        == 1
    )

    assert (
        result.entries[2].objection
        == "Worried about onboarding"
    )

    assert (
        result.entries[2].response
        is None
    )


def test_duplicate_objections_are_not_collapsed():
    lines = [
        "- Too expensive",
        "resp: Start small.",
        "- Too expensive",
        "resp: Offer a pilot.",
    ]

    result = parse_objection_notes(
        lines
    )

    assert result.objection_count == 2

    assert (
        result.entries[0].entry_id
        != result.entries[1].entry_id
    )


def test_orphan_response_is_preserved_as_warning():
    lines = [
        "resp: This has no objection.",
    ]

    result = parse_objection_notes(
        lines
    )

    assert result.objection_count == 0

    assert (
        len(
            result.unassigned_source_ids
        )
        == 1
    )

    assert result.warnings


def test_source_ids_are_preserved():
    lines = [
        "- Security?",
        (
            "resp: Data is encrypted."
        ),
    ]

    result = parse_objection_notes(
        lines
    )

    entry = result.entries[0]

    assert (
        entry.objection_source_ids
        == ["SRC-001"]
    )

    assert (
        entry.response_source_ids
        == ["SRC-002"]
    )


def test_missing_response_is_never_invented():
    result = parse_objection_notes(
        [
            "- Implementation looks complicated",
        ]
    )

    entry = result.entries[0]

    assert (
        entry.status
        == EntryStatus.MISSING_RESPONSE
    )

    assert entry.response is None