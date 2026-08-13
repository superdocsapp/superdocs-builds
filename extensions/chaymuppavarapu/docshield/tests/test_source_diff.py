from src.source_diff import diff_source_structure


def test_identical_structures_have_no_changes():
    structure = {
        "format": "latex",
        "packages": ["geometry", "hyperref"],
        "sections": ["Experience", "Education"],
    }

    result = diff_source_structure(
        structure,
        structure,
    )

    assert result.changed is False
    assert result.change_count == 0


def test_added_structure_is_detected():
    before = {
        "packages": ["geometry"],
    }

    after = {
        "packages": ["geometry", "hyperref"],
    }

    result = diff_source_structure(
        before,
        after,
    )

    assert result.changed is True
    assert result.change_count == 1
    assert result.changes[0].category == "added"


def test_removed_structure_is_detected():
    before = {
        "packages": ["geometry", "hyperref"],
    }

    after = {
        "packages": ["geometry"],
    }

    result = diff_source_structure(
        before,
        after,
    )

    assert result.changed is True
    assert result.changes[0].category == "removed"


def test_formatting_change_is_detected():
    before = {
        "font_size": 10,
        "margin": 20,
    }

    after = {
        "font_size": 12,
        "margin": 20,
    }

    result = diff_source_structure(
        before,
        after,
    )

    assert result.changed is True
    assert result.changes[0].category == "changed"
    assert result.changes[0].path == "root.font_size"


def test_nested_change_is_detected():
    before = {
        "sections": {
            "experience": {
                "heading_level": 1,
            }
        }
    }

    after = {
        "sections": {
            "experience": {
                "heading_level": 2,
            }
        }
    }

    result = diff_source_structure(
        before,
        after,
    )

    assert result.changed is True
    assert (
        result.changes[0].path
        == "root.sections.experience.heading_level"
    )


def test_list_reordering_is_detected():
    before = {
        "sections": [
            "Experience",
            "Education",
        ]
    }

    after = {
        "sections": [
            "Education",
            "Experience",
        ]
    }

    result = diff_source_structure(
        before,
        after,
    )

    assert result.changed is True
    assert result.change_count == 2
