import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from flow_diagram import compute_derived_counts, validate_counts

GOOD_COUNTS = {
    "databases": [{"name": "PubMed", "records_identified": 100}],
    "other_sources_identified": 0,
    "duplicates_removed": 10,
    "records_screened_title_abstract": 90,
    "records_excluded_title_abstract": 60,
    "reports_sought_for_retrieval": 30,
    "reports_not_retrieved": 2,
    "reports_assessed_full_text": 28,
    "reports_excluded_full_text": [{"reason": "Wrong population", "count": 8}],
    "studies_included_in_review": 20,
    "studies_included_in_synthesis": 18,
}


def test_consistent_counts_pass_validation():
    assert validate_counts(GOOD_COUNTS) == []


def test_inconsistent_screened_count_is_caught():
    bad = dict(GOOD_COUNTS)
    bad["records_screened_title_abstract"] = 999  # deliberately wrong
    errors = validate_counts(bad)
    assert len(errors) >= 1
    assert "screened" in errors[0]


def test_synthesis_cannot_exceed_review():
    bad = dict(GOOD_COUNTS)
    bad["studies_included_in_synthesis"] = 999  # more than included_review
    errors = validate_counts(bad)
    assert any("included_synthesis" in e for e in errors)


def test_derived_counts_arithmetic():
    d = compute_derived_counts(GOOD_COUNTS)
    assert d["total_identified"] == 100
    assert d["excluded_full_text_total"] == 8
