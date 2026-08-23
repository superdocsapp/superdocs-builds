"""
test_preservation_checker.py
Tests for scientific content preservation checking.
"""
import pytest
from preservation_checker import (
    check_preservation,
    _extract_numbers,
    _extract_statistical_markers,
    _extract_equations,
    _extract_citation_refs,
    CHECKER_LIMITATION,
)


class TestExtractNumbers:
    def test_extracts_integers(self):
        nums = _extract_numbers("We used 45 samples and 3 replicates.")
        assert "45" in nums
        assert "3" in nums

    def test_extracts_decimals(self):
        nums = _extract_numbers("The value was 3.14 and 0.05.")
        assert "3.14" in nums
        assert "0.05" in nums

    def test_extracts_percentages(self):
        nums = _extract_numbers("Viability improved by 34%.")
        assert "34%" in nums

    def test_extracts_scientific_notation(self):
        nums = _extract_numbers("Concentration was 1.5e-3 M.")
        assert "1.5e-3" in nums

    def test_empty_text(self):
        assert _extract_numbers("") == []


class TestExtractStatisticalMarkers:
    def test_extracts_p_value(self):
        stats = _extract_statistical_markers("p < 0.001 was considered significant.")
        assert any("p" in s.lower() for s in stats)

    def test_extracts_n_equals(self):
        stats = _extract_statistical_markers("n=45 per group")
        assert any("n" in s.lower() for s in stats)

    def test_extracts_f_statistic(self):
        stats = _extract_statistical_markers("F(3,176) = 47.3")
        assert any("F" in s for s in stats)

    def test_extracts_correlation(self):
        stats = _extract_statistical_markers("r = 0.85 between variables")
        assert any("r" in s.lower() for s in stats)

    def test_empty_text(self):
        assert _extract_statistical_markers("") == []


class TestExtractEquations:
    def test_extracts_latex_inline(self):
        html = "<p>The formula $F = ma$ applies here.</p>"
        eqs = _extract_equations(html)
        assert any("F = ma" in e for e in eqs)

    def test_extracts_latex_display(self):
        html = "<p>$$E = mc^2$$</p>"
        eqs = _extract_equations(html)
        assert any("E = mc^2" in e for e in eqs)

    def test_no_equations(self):
        html = "<p>No equations here.</p>"
        eqs = _extract_equations(html)
        assert eqs == []


class TestExtractCitationRefs:
    def test_extracts_numbered_citations(self):
        text = "As shown previously [1,2,3]."
        cites = _extract_citation_refs(text)
        assert any("[1,2,3]" in c for c in cites)

    def test_extracts_author_year(self):
        text = "As reported by (Smith et al., 2020)."
        cites = _extract_citation_refs(text)
        assert any("Smith" in c for c in cites)


class TestCheckPreservation:
    def test_identical_html_no_concerns(self, sample_original_html):
        result = check_preservation(sample_original_html, sample_original_html)
        assert result["has_concerns"] is False
        assert result["numbers_missing"] == []
        assert result["stats_missing"] == []
        assert result["equations_missing"] == []

    def test_missing_number_flagged(self, sample_original_html):
        # Remove a specific number from the transformed version
        transformed = sample_original_html.replace("58%", "REMOVED")
        result = check_preservation(sample_original_html, transformed)
        assert result["has_concerns"] is True
        assert any("58" in n for n in result["numbers_missing"])

    def test_missing_p_value_flagged(self, sample_original_html):
        transformed = sample_original_html.replace("p &lt; 0.001", "REMOVED")
        result = check_preservation(sample_original_html, transformed)
        assert result["has_concerns"] is True
        assert len(result["stats_missing"]) > 0

    def test_missing_equation_flagged(self, sample_original_html):
        transformed = sample_original_html.replace(
            "$F = N_{individual} / N_{total}$", ""
        )
        result = check_preservation(sample_original_html, transformed)
        assert result["has_concerns"] is True
        assert len(result["equations_missing"]) > 0

    def test_added_numbers_reported(self, sample_original_html):
        transformed = sample_original_html + "<p>New value: 9999</p>"
        result = check_preservation(sample_original_html, transformed)
        assert "9999" in result["numbers_added"]

    def test_result_contains_limitation_notice(self, sample_original_html):
        result = check_preservation(sample_original_html, sample_original_html)
        assert result["limitation_notice"] == CHECKER_LIMITATION

    def test_result_contains_summary(self, sample_original_html):
        result = check_preservation(sample_original_html, sample_original_html)
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0

    def test_empty_transformed_html_flags_all(self, sample_original_html):
        result = check_preservation(sample_original_html, "")
        assert result["has_concerns"] is True

    def test_structural_change_no_false_positive_on_numbers(self):
        # Reordering sections should not flag number changes
        original = "<h2>Results</h2><p>n=45, p=0.001</p><h2>Methods</h2><p>n=45, p=0.001</p>"
        transformed = "<h2>Methods</h2><p>n=45, p=0.001</p><h2>Results</h2><p>n=45, p=0.001</p>"
        result = check_preservation(original, transformed)
        # Numbers are the same, just reordered — should not flag
        assert result["numbers_missing"] == []
        assert result["stats_missing"] == []
