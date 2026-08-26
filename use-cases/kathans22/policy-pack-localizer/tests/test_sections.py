"""Proves parse_sections rejects a document with a repeated section
number rather than silently keeping whichever occurrence a later
dict-comprehension lookup happens to land on."""

from __future__ import annotations

from localizer import sections


def test_parse_sections_parses_a_well_formed_document():
    text = "## 1 Purpose\n\nBody one.\n\n## 2 Scope\n\nBody two.\n"

    parsed = sections.parse_sections(text)

    assert [s["number"] for s in parsed] == [1, 2]
    assert parsed[0]["heading"] == "Purpose"
    assert parsed[0]["body"] == "Body one."


def test_parse_sections_rejects_a_duplicated_document():
    # Reproduces the live bug: a SuperDocs export call duplicated an entire
    # pack (every section repeated several times), which used to slip
    # through undetected because nothing downstream checked for it.
    text = "## 1 Purpose\n\nBody one.\n\n## 1 Purpose\n\nBody one again.\n"

    raised = False
    try:
        sections.parse_sections(text)
    except ValueError as exc:
        raised = True
        assert "[1]" in str(exc)
    assert raised


def test_parse_sections_collapses_a_verbatim_whole_document_duplicate():
    # Reproduces the real live failure (Brazil, Kenya rollouts): a flaky
    # SuperDocs export repeated the entire, already-correctly-edited
    # document verbatim, several times over (9 sections became 72 headings
    # across compounding export calls). Every copy of every section is
    # byte-identical, so this is unambiguous and must recover silently
    # rather than quarantine a pack whose real content was fine.
    text = "## 1 Purpose\n\nBody one.\n\n## 2 Scope\n\nBody two.\n"
    duplicated = text + text + text

    parsed = sections.parse_sections(duplicated)

    assert [s["number"] for s in parsed] == [1, 2]
    assert parsed[0]["body"] == "Body one."
    assert parsed[1]["body"] == "Body two."


def test_parse_sections_names_only_the_actually_duplicated_numbers():
    text = (
        "## 1 Purpose\n\nBody.\n\n"
        "## 2 Scope\n\nBody.\n\n"
        "## 2 Scope\n\nBody again.\n"
    )

    raised = False
    try:
        sections.parse_sections(text)
    except ValueError as exc:
        raised = True
        message = str(exc)
        assert "[2]" in message
        assert "[1" not in message
    assert raised
