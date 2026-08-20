import pytest

from superdocs.parser import (
    SuperDocsParseError,
    parse_pending_changes,
)


def test_pending_changes_accepts_list():
    changes = [
        {
            "change_id": "change-1",
            "operation": "replace",
        }
    ]

    assert (
        parse_pending_changes(changes)
        == changes
    )


def test_pending_changes_parses_json_encoded_string():
    raw = """
    [
      {
        "change_id": "change-1",
        "operation": "replace"
      }
    ]
    """

    result = parse_pending_changes(
        raw
    )

    assert len(result) == 1

    assert (
        result[0]["change_id"]
        == "change-1"
    )


def test_bad_json_does_not_become_empty_changes():
    with pytest.raises(
        SuperDocsParseError
    ):
        parse_pending_changes(
            "[broken"
        )

from superdocs.parser import (
    pending_changes_from_job,
)


def test_pending_changes_found_inside_job_metadata():
    job = {
        "status": "awaiting_approval",
        "metadata": {
            "pending_changes": [
                {
                    "operation": "replace",
                    "old_html": "<p>Before</p>",
                    "new_html": "<p>After</p>",
                }
            ]
        },
    }

    changes = pending_changes_from_job(
        job
    )

    assert len(changes) == 1
    assert (
        changes[0]["operation"]
        == "replace"
    )


def test_metadata_pending_changes_can_be_json_string():
    job = {
        "status": "awaiting_approval",
        "metadata": {
            "pending_changes": (
                '[{"operation":"replace"}]'
            )
        },
    }

    changes = pending_changes_from_job(
        job
    )

    assert len(changes) == 1
    assert (
        changes[0]["operation"]
        == "replace"
    )