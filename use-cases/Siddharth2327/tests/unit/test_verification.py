from winloss_superdocs.verification import (
    verify_evidence_quotes,
    verify_synthesis_numbers,
)


def test_all_quotes_grounded_in_transcript(valid_debrief_html, sample_transcript):
    result = verify_evidence_quotes(valid_debrief_html, sample_transcript)
    assert result.total_quotes == 5  # matches VALID_DEBRIEF_HTML fixture's blockquote count
    assert result.all_grounded
    assert result.unverified_quotes == []


def test_fabricated_quote_is_flagged_not_silently_kept(debrief_html_with_fabricated_quote, sample_transcript):
    result = verify_evidence_quotes(debrief_html_with_fabricated_quote, sample_transcript)
    assert not result.all_grounded
    assert any("CEO personally guaranteed" in q for q in result.unverified_quotes)
    # Grounded quotes elsewhere in the same doc are still recognized as grounded.
    assert any("deciding factor" in q for q in result.grounded_quotes)


def test_empty_transcript_grounds_nothing():
    from winloss_superdocs.verification import verify_evidence_quotes

    html = '<blockquote data-evidence="true">anything at all</blockquote>'
    result = verify_evidence_quotes(html, "")
    assert result.unverified_quotes == ["anything at all"]


def test_synthesis_numbers_match(valid_brief_html):
    expected = {"Comp Corp": (1, 1), "Mid-Market": (1, 1)}
    result = verify_synthesis_numbers(valid_brief_html, expected)
    assert result.ok
    assert result.mismatches == []


def test_synthesis_numbers_mismatch_detected(valid_brief_html):
    expected = {"Comp Corp": (5, 5)}  # wrong on purpose
    result = verify_synthesis_numbers(valid_brief_html, expected)
    assert not result.ok
    assert "Comp Corp" in result.mismatches[0]


def test_synthesis_numbers_missing_row_detected(valid_brief_html):
    expected = {"Nonexistent Competitor": (1, 1)}
    result = verify_synthesis_numbers(valid_brief_html, expected)
    assert not result.ok
    assert "no matching table row" in result.mismatches[0]
