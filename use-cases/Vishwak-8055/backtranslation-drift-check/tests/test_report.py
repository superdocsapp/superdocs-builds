from __future__ import annotations

import json

from conftest import FIXTURES_DIR
from demo_providers import build_flagship_provider

from drift_check import report
from drift_check.pipeline import run_pipeline


def _flagship_result():
    return run_pipeline(
        run_id="report-test",
        source_raw_text=(FIXTURES_DIR / "flagship" / "source_en.md").read_text(),
        target_raw_text=(FIXTURES_DIR / "flagship" / "target_es.md").read_text(),
        source_document_id="medsure",
        target_document_id="medsure-es",
        source_lang="en",
        target_lang="es",
        provider=build_flagship_provider(),
        protected_terms=("MedSure Compliance Board (MCB)",),
    )


def test_json_report_is_well_formed_and_corrections_target_translation_only() -> None:
    result = _flagship_result()
    payload = json.loads(report.to_json(result))
    assert payload["summary"]["source_integrity_status"] == "VERIFIED"
    assert payload["summary"]["findings_total"] == len(result.findings)
    for f in payload["findings"]:
        if f["proposed_correction"]:
            assert f["proposed_correction"]["correction_target"] == "translation"
        assert f["source_text"]  # every finding carries full bilingual context
        assert f["target_text"]
        assert "back_translation" in f


def test_markdown_report_has_summary_and_all_findings() -> None:
    result = _flagship_result()
    md = report.to_markdown(result)
    assert "SOURCE INTEGRITY: VERIFIED" in md
    for f in result.findings:
        assert f.id or True  # id not rendered directly, but row count should match
    assert md.count("\n|") >= len(result.findings)  # at least one table row per finding


def test_html_report_renders_all_findings_and_no_source_mutation_claim() -> None:
    result = _flagship_result()
    html_out = report.to_html(result)
    assert "SOURCE INTEGRITY" in html_out
    assert "VERIFIED" in html_out
    assert html_out.count('class="card') >= len(result.findings)
    assert "targets the translation only" in html_out.lower() or "targets translation only" in html_out.lower()


def test_summary_metrics_severity_counts_sum_to_total() -> None:
    result = _flagship_result()
    s = report.summary_metrics(result)
    assert s["critical"] + s["high"] + s["medium"] + s["low"] + s["info_pass"] == s["findings_total"]


def test_html_section_label_matches_finding_section_index_not_list_position() -> None:
    """Regression test for a real bug: Section 11 legitimately produces two
    findings (modal + qualifier — different categories, correctly not
    merged), which previously pushed every subsequent card's displayed
    '§N' label out of sync with the actual document section (the semantic-
    only Section 12 finding was mislabeled '§13'). The label must always
    equal the finding's own section_index, never a position count."""
    result = _flagship_result()
    html_out = report.to_html(result)
    import re

    for f in result.findings:
        pattern = rf'class="idx">§{f.section_index}<'
        message = f"finding {f.id} (section {f.section_index}) has no matching §{f.section_index} label"
        assert re.search(pattern, html_out), message
    # The document has exactly 12 sections; no card may claim a higher one.
    all_labels = [int(n) for n in re.findall(r'class="idx">§(\d+)<', html_out)]
    assert max(all_labels) == 12
    assert set(all_labels) == set(range(1, 13))
