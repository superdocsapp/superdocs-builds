from pathlib import Path

from winloss_superdocs.index import (
    DebriefRecord,
    Index,
    aggregate_competitor_stats,
    aggregate_segment_stats,
    parse_debrief_html,
)


def make_record(deal_code, quarter, segment, outcome, competitors):
    return DebriefRecord(
        deal_code=deal_code,
        quarter=quarter,
        segment=segment,
        outcome=outcome,
        competitors=competitors,
        customer_name=f"Customer of {deal_code}",
        transcript_sha256="abc123",
    )


def test_upsert_and_get(tmp_path):
    idx = Index(tmp_path / "index.json")
    rec = make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"])
    idx.upsert(rec)
    assert idx.get("DEAL-1").outcome == "win"


def test_upsert_is_idempotent_by_deal_code(tmp_path):
    idx = Index(tmp_path / "index.json")
    idx.upsert(make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"]))
    idx.upsert(make_record("DEAL-1", "2025Q4", "Mid-Market", "loss", ["Comp Corp"]))  # re-index
    assert len(idx.all()) == 1
    assert idx.get("DEAL-1").outcome == "loss"


def test_persists_across_instances(tmp_path):
    path = tmp_path / "index.json"
    idx1 = Index(path)
    idx1.upsert(make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"]))
    idx2 = Index(path)  # fresh load
    assert idx2.get("DEAL-1") is not None


def test_for_quarter_filters(tmp_path):
    idx = Index(tmp_path / "index.json")
    idx.upsert(make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"]))
    idx.upsert(make_record("DEAL-2", "2025Q3", "Mid-Market", "loss", ["Comp Corp"]))
    assert [r.deal_code for r in idx.for_quarter("2025Q4")] == ["DEAL-1"]


def test_by_competitor_case_insensitive(tmp_path):
    idx = Index(tmp_path / "index.json")
    idx.upsert(make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"]))
    assert [r.deal_code for r in idx.by_competitor("comp corp")] == ["DEAL-1"]


def test_all_customer_terms_dedupes(tmp_path):
    idx = Index(tmp_path / "index.json")
    r1 = make_record("DEAL-1", "2025Q4", "Mid-Market", "win", [])
    r1.customer_name = "Acme Robotics Inc."
    r1.customer_aliases = ["Acme"]
    r2 = make_record("DEAL-2", "2025Q4", "Mid-Market", "loss", [])
    r2.customer_name = "Acme Robotics Inc."  # same customer, two deals
    idx.upsert(r1)
    idx.upsert(r2)
    terms = idx.all_customer_terms()
    assert terms.count("Acme Robotics Inc.") == 1
    assert "Acme" in terms


def test_aggregate_competitor_stats_and_small_sample_flag():
    records = [
        make_record("DEAL-1", "2025Q4", "Mid-Market", "win", ["Comp Corp"]),
        make_record("DEAL-2", "2025Q4", "Enterprise", "loss", ["Comp Corp"]),
        make_record("DEAL-3", "2025Q4", "Enterprise", "loss", ["Rare Rival"]),
    ]
    stats = aggregate_competitor_stats(records, small_sample_threshold=3)
    by_name = {s.competitor: s for s in stats}
    assert by_name["Comp Corp"].wins_against == 1
    assert by_name["Comp Corp"].losses_to == 1
    assert by_name["Comp Corp"].small_sample is True  # n=2 < 3
    assert by_name["Rare Rival"].small_sample is True  # n=1 < 3


def test_aggregate_competitor_stats_not_small_sample_above_threshold():
    records = [
        make_record(f"DEAL-{i}", "2025Q4", "Mid-Market", "win" if i % 2 else "loss", ["Comp Corp"])
        for i in range(4)
    ]
    stats = aggregate_competitor_stats(records, small_sample_threshold=3)
    assert stats[0].small_sample is False  # n=4 >= 3


def test_aggregate_segment_stats():
    records = [
        make_record("DEAL-1", "2025Q4", "Mid-Market", "win", []),
        make_record("DEAL-2", "2025Q4", "Mid-Market", "loss", []),
    ]
    stats = aggregate_segment_stats(records, small_sample_threshold=3)
    assert stats[0].segment == "Mid-Market"
    assert stats[0].wins == 1
    assert stats[0].losses == 1
    assert stats[0].small_sample is True


def test_parse_debrief_html_extracts_competitors_and_evidence(valid_debrief_html):
    parsed = parse_debrief_html(valid_debrief_html)
    assert parsed["competitors"] == ["Comp Corp"]
    assert len(parsed["evidence_snippets"]) == 5


def test_parse_debrief_html_no_competitors_mentioned():
    html = """
    <h2>Competitors Present</h2>
    <table><tr><th>Competitor</th></tr><tr><td>None mentioned in transcript</td></tr></table>
    """
    parsed = parse_debrief_html(html)
    assert parsed["competitors"] == []
