from winloss_superdocs.schema import (
    SchemaValidationError,
    check_brief_schema,
    check_debrief_schema,
)


def test_valid_debrief_passes(valid_debrief_html):
    result = check_debrief_schema(valid_debrief_html)
    assert result.ok
    assert result.missing_sections == []


def test_missing_section_fails(debrief_html_missing_section):
    result = check_debrief_schema(debrief_html_missing_section)
    assert not result.ok
    assert "Deciding Factor" in result.missing_sections


def test_raise_if_failed_raises_with_useful_message(debrief_html_missing_section):
    result = check_debrief_schema(debrief_html_missing_section)
    try:
        result.raise_if_failed("Debrief DEAL-TEST")
        assert False, "expected SchemaValidationError"
    except SchemaValidationError as e:
        assert "Deciding Factor" in str(e)
        assert "DEAL-TEST" in str(e)


def test_valid_brief_passes(valid_brief_html):
    result = check_brief_schema(valid_brief_html)
    assert result.ok


def test_brief_missing_section_fails():
    html = "<h1>x</h1><h2>Overview &amp; Methodology</h2><p>only one section</p>"
    result = check_brief_schema(html)
    assert not result.ok
    assert len(result.missing_sections) == 4
