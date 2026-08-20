"""Report generation tests: markdown structure on the fixture tree, the
markdown->HTML converter (including the multi-bold regression), and the
no-sheets branch."""

import pytest

from app.report import _md_to_html, build_report, build_report_html


class TestBuildReport:
    def test_sections_present(self, tree):
        md = build_report()
        for marker in ("## 1.", "## 2. Method", "## 3. Budget guard", "## 4. Actual spend",
                       "## 5. Scores", "## 6. Inter-rater agreement", "## 7. Disagreement review",
                       "## 8. Honest limitations", "## 9. Reproduce"):
            assert marker in md, f"missing section {marker}"

    def test_scores_table_lists_case_and_dimensions(self, tree):
        md = build_report()
        assert "| plan-01 | easy |" in md
        for did in ("faithfulness", "fact_accuracy", "content_preservation",
                    "structural_integrity", "formatting_fidelity", "language_quality"):
            assert f"| {did} |" in md

    def test_ledger_table_lists_calls(self, tree):
        md = build_report()
        assert "| time (UTC) | endpoint | tag | billable | ops | remaining |" in md
        assert "edit:plan-01" in md

    def test_agreement_section_with_sheets(self, tree):
        md = build_report()
        assert "**Overall:**" in md
        assert "Cohen's kappa" in md
        assert "Confusion matrices" in md
        assert "score distribution" in md.lower()

    def test_no_sheets_branch(self, tree):
        for p in (tree["human"] / "plan-01.json", tree["auto"] / "plan-01.json"):
            p.unlink()
        md = build_report()
        assert "Agreement statistics are computed once both raters" in md

    def test_spend_reported(self, tree):
        md = build_report()
        assert "**Spent: 1 operations**" in md
        assert "(cap 60)" in md

    def test_report_matches_html_conversion(self, tree):
        md = build_report()
        html = build_report_html()
        assert "<html>" in html and "<body>" in html
        assert "**" not in html  # no unrendered bold


class TestMdToHtml:
    def test_multiple_bold_pairs_per_line(self):
        # regression: only the first ** pair used to be converted
        out = _md_to_html("**Overall:** kappa **0.339** and **0.405** here.")
        assert "<b>Overall:</b> kappa <b>0.339</b> and <b>0.405</b> here." in out
        assert "**" not in out

    def test_headers(self):
        out = _md_to_html("# H1\n## H2\n### H3\n#### H4")
        assert "<h1>H1</h1>" in out
        assert "<h2>H2</h2>" in out
        assert "<h3>H3</h3>" in out
        assert "<h4>H4</h4>" in out

    def test_table(self):
        md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
        out = _md_to_html(md)
        assert "<table>" in out
        assert "<th>a</th>" in out and "<th>b</th>" in out
        assert "<td>1</td>" in out and "<td>2</td>" in out

    def test_inline_code_and_fence(self):
        out = _md_to_html("Run `python x.py`.\n\n```bash\npip install\n```")
        assert "<code>python x.py</code>" in out
        assert "<pre>" in out and "pip install" in out

    def test_escaping(self):
        out = _md_to_html("a < b & c > d")
        assert "&lt;" in out and "&amp;" in out and "&gt;" in out

    def test_list_items_and_paragraphs(self):
        out = _md_to_html("- one\n- two\n\nplain paragraph")
        assert "<li>one</li>" in out and "<li>two</li>" in out
        assert "<p>plain paragraph</p>" in out

    def test_empty_input(self):
        assert _md_to_html("") == ""
        assert _md_to_html("\n\n") == ""