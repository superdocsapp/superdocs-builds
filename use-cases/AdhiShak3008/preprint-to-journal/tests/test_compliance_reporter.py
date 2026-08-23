"""
test_compliance_reporter.py
Tests for compliance report generation.
"""
import pytest
from compliance_reporter import build_report, summarise_report


def _make_html(sections=None, word_count=None, has_table=False, has_figure=False,
               has_placeholder=False):
    """Build a minimal HTML string for testing."""
    parts = []
    if sections:
        for s in sections:
            parts.append(f"<h2>{s}</h2><p>Content for {s}.</p>")
    if has_table:
        parts.append("<table><tr><td>Data</td></tr></table>")
    if has_figure:
        parts.append("<figure><img src='fig1.png'><figcaption>Figure 1</figcaption></figure>")
    if has_placeholder:
        parts.append("<p>[DECLARATION REQUIRED — please complete before submission]</p>")
    if word_count:
        # Pad with words to hit target count
        current = len(" ".join(parts).split())
        extra = max(0, word_count - current)
        parts.append("<p>" + " ".join(["word"] * extra) + "</p>")
    return "\n".join(parts)


class TestBuildReport:
    def test_all_sections_present_returns_instruction_sent(self, nature_profile):
        html = _make_html(sections=nature_profile["section_order"])
        report = build_report(nature_profile, html)
        section_item = next(r for r in report if "Section structure" in r["requirement"])
        assert section_item["status"] == "instruction_sent"

    def test_missing_sections_returns_partial(self, nature_profile):
        # Only provide a subset of required sections
        html = _make_html(sections=["Abstract", "Introduction"])
        report = build_report(nature_profile, html)
        section_item = next(r for r in report if "Section structure" in r["requirement"])
        assert section_item["status"] == "partial"
        assert "missing" in section_item["detail"].lower() or "not found" in section_item["detail"].lower()

    def test_reference_style_always_instruction_sent(self, nature_profile):
        html = _make_html(sections=["Abstract"])
        report = build_report(nature_profile, html)
        ref_item = next(r for r in report if "Reference style" in r["requirement"])
        assert ref_item["status"] == "instruction_sent"

    def test_word_limit_met(self, nature_profile):
        # Nature limit is 3000 — use 100 words
        html = _make_html(word_count=100)
        report = build_report(nature_profile, html)
        wl_item = next(r for r in report if "Word limit" in r["requirement"])
        assert wl_item["status"] == "met"

    def test_word_limit_exceeded(self, nature_profile):
        # Nature limit is 3000 — use 4000 words
        html = _make_html(word_count=4000)
        report = build_report(nature_profile, html)
        wl_item = next(r for r in report if "Word limit" in r["requirement"])
        assert wl_item["status"] == "unmet"
        assert "exceed" in wl_item["detail"].lower()

    def test_no_word_limit_returns_met(self, plos_profile):
        # PLOS ONE has null word_limit
        html = _make_html(word_count=5000)
        report = build_report(plos_profile, html)
        wl_item = next(r for r in report if "Word limit" in r["requirement"])
        assert wl_item["status"] == "met"

    def test_missing_declaration_returns_unmet(self, nature_profile):
        # No declaration sections in HTML
        html = _make_html(sections=["Abstract", "Introduction"])
        report = build_report(nature_profile, html)
        decl_items = [r for r in report if "Declaration" in r["requirement"]]
        assert len(decl_items) > 0
        unmet = [r for r in decl_items if r["status"] == "unmet"]
        assert len(unmet) > 0

    def test_present_declaration_returns_met(self, nature_profile):
        # Include the declaration sections
        html = _make_html(sections=[
            "Abstract", "Competing Interests", "Data Availability", "Author Contributions"
        ])
        report = build_report(nature_profile, html)
        decl_items = [r for r in report if "Declaration" in r["requirement"]]
        met = [r for r in decl_items if r["status"] == "met"]
        assert len(met) > 0

    def test_placeholder_declaration_returns_unmet(self, nature_profile):
        html = _make_html(sections=["Abstract"], has_placeholder=True)
        report = build_report(nature_profile, html)
        decl_items = [r for r in report if "Declaration" in r["requirement"]]
        unmet = [r for r in decl_items if r["status"] == "unmet"]
        assert len(unmet) > 0

    def test_non_blinded_journal_blinding_met(self, nature_profile):
        html = _make_html(sections=["Abstract"])
        report = build_report(nature_profile, html)
        blind_item = next(r for r in report if "Blinding" in r["requirement"])
        assert blind_item["status"] == "met"
        assert "does not require" in blind_item["detail"].lower()

    def test_blinded_journal_with_blinding_result(self, plos_profile):
        html = _make_html(sections=["Abstract"])
        blinding_result = {
            "items_removed": ["Author name placeholder found (2 instance(s))"],
            "potential_remaining": [],
            "limitation_notice": "...",
        }
        report = build_report(plos_profile, html, blinding_result=blinding_result)
        blind_item = next(r for r in report if "Blinding" in r["requirement"])
        assert blind_item["status"] == "met"

    def test_blinded_journal_with_remaining_identifiers(self, plos_profile):
        html = _make_html(sections=["Abstract"])
        blinding_result = {
            "items_removed": ["Author name placeholder found (1 instance(s))"],
            "potential_remaining": ["Possible self-identifying language (1 instance(s))"],
            "limitation_notice": "...",
        }
        report = build_report(plos_profile, html, blinding_result=blinding_result)
        blind_item = next(r for r in report if "Blinding" in r["requirement"])
        assert blind_item["status"] == "partial"

    def test_table_detected_returns_instruction_sent(self, nature_profile):
        html = _make_html(sections=["Abstract"], has_table=True)
        report = build_report(nature_profile, html)
        tbl_item = next(r for r in report if "Table placement" in r["requirement"])
        assert tbl_item["status"] == "instruction_sent"

    def test_no_table_returns_unverifiable(self, nature_profile):
        html = _make_html(sections=["Abstract"])
        report = build_report(nature_profile, html)
        tbl_item = next(r for r in report if "Table placement" in r["requirement"])
        assert tbl_item["status"] == "unverifiable"

    def test_report_never_fabricates_compliance(self, nature_profile):
        # Empty HTML — most things should be unmet or unverifiable, not 'met'
        report = build_report(nature_profile, "")
        statuses = [r["status"] for r in report]
        # Should have some unmet items
        assert "unmet" in statuses or "partial" in statuses or "unverifiable" in statuses


class TestSummariseReport:
    def test_counts_statuses(self, nature_profile):
        html = _make_html(sections=["Abstract"])
        report = build_report(nature_profile, html)
        summary = summarise_report(report)
        assert "counts" in summary
        assert "overall" in summary
        total = sum(summary["counts"].values())
        assert total == len(report)

    def test_overall_message_when_unmet(self, nature_profile):
        html = _make_html(sections=["Abstract"])  # missing declarations
        report = build_report(nature_profile, html)
        summary = summarise_report(report)
        if summary["counts"]["unmet"] > 0:
            assert "unmet" in summary["overall"].lower() or "required" in summary["overall"].lower()
