"""The double-parse gotcha, and the class of problem around it.

SuperDocs sometimes returns a change list as a JSON-encoded string. Integrators
who miss that see empty diff cards with every field undefined. These tests pin
the behaviour so a refactor cannot quietly reintroduce it.
"""

import json

import pytest

from superdocs_kit.changes import Change, changes_from, deep_parse, updated_html_from

CHANGE = {
    "change_id": "c1",
    "operation": "edit",
    "chunk_id": "abc",
    "document_id": "doc_primary",
    "old_html": "<p>old</p>",
    "new_html": "<p>new</p>",
    "ai_explanation": "changed it",
}


def test_plain_list_of_changes():
    out = changes_from({"document_changes": {"pending_changes": [CHANGE]}})
    assert [c.new_html for c in out] == ["<p>new</p>"]


def test_json_encoded_string_is_parsed_once():
    payload = {"document_changes": {"pending_changes": json.dumps([CHANGE])}}
    out = changes_from(payload)
    assert len(out) == 1 and out[0].chunk_id == "abc"


def test_double_encoded_string_is_parsed_twice():
    """The failure mode the brief warns about: a string containing a string."""
    payload = {"document_changes": {"pending_changes": json.dumps(json.dumps([CHANGE]))}}
    out = changes_from(payload)
    assert len(out) == 1 and out[0].new_html == "<p>new</p>"


def test_changes_found_in_every_container_the_api_uses():
    for payload in (
        {"document_changes": {"chunk_diffs": [CHANGE]}},
        {"result": {"document_changes": {"pending_changes": [CHANGE]}}},
        {"metadata": {"pending_changes": [CHANGE]}},
        {"document_changes": {"changes": [CHANGE]}},
        [CHANGE],
        json.dumps([CHANGE]),
    ):
        assert len(changes_from(payload)) == 1, payload


def test_no_changes_is_an_empty_list_not_an_exception():
    """'Nothing changed' is a normal answer and must not look like a crash."""
    assert changes_from({"response": "nothing to do"}) == []
    assert changes_from(None) == []
    assert changes_from({"document_changes": None}) == []


def test_duplicates_are_collapsed():
    payload = {"document_changes": {"pending_changes": [CHANGE], "chunk_diffs": [CHANGE]}}
    assert len(changes_from(payload)) == 1


def test_deep_parse_leaves_ordinary_prose_alone():
    assert deep_parse("A sentence with [brackets] in it.") == "A sentence with [brackets] in it."
    assert deep_parse("{not json") == "{not json"


def test_deep_parse_is_bounded():
    """A pathological input must terminate, not recurse forever.

    Twelve levels, not fifty: each json.dumps roughly doubles the escaping, so
    fifty levels is a petabyte-scale string and the test hangs building its own
    input. (It did. That was my bug, and it is why the number is small and
    commented rather than large and impressive.)
    """
    nested = "1"
    for _ in range(12):
        nested = json.dumps(nested)
    assert deep_parse(nested) is not None


def test_change_from_a_bare_string_does_not_explode():
    assert Change.from_dict({"change_id": "x", "operation": "edit"}).new_html is None


@pytest.mark.parametrize("path", [
    {"document_changes": {"updated_html": "<h1>x</h1>"}},
    {"result": {"document_changes": {"updated_html": "<h1>x</h1>"}}},
    {"updated_html": "<h1>x</h1>"},
])
def test_updated_html_found_wherever_it_lives(path):
    assert updated_html_from(path) == "<h1>x</h1>"


def test_updated_html_absent_is_none_not_empty_string():
    """Distinguishing 'compact mode, no HTML' from 'empty document' matters."""
    assert updated_html_from({"document_changes": {"updated_html": None}}) is None
