"""The command line: exit codes, and the promise that four of five commands
never touch the network.

Exit codes matter because this is meant to run in CI as a compliance gate:
0 = ok, 1 = bad input, 2 = refused (blocking findings), 3 = inconsistent pack.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from real_estate_pack.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CURRENT = "2025-09-01"  # before every shipped review date


def run(argv):
    return main(argv)


# ------------------------------------------------------------------ exit codes


def test_check_returns_zero_on_a_clean_record(capsys):
    assert run(["check", str(EXAMPLES / "tx_austin_apartment.yaml")]) == 0
    assert "OK to draft" in capsys.readouterr().out


def test_check_returns_two_when_it_refuses(capsys):
    assert run(["check", str(EXAMPLES / "incomplete_ca_unanswered.yaml")]) == 2
    out = capsys.readouterr().out
    assert "REFUSING TO DRAFT" in out
    assert "No API call was made and no operation was spent" in out


def test_draft_without_an_api_key_fails_cleanly_rather_than_traceback(capsys, tmp_path, monkeypatch):
    """A missing key is an ordinary operating condition. A traceback would bury
    the one sentence that says what to do about it."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    code = run(["draft", str(EXAMPLES / "tx_austin_apartment.yaml"),
                "--template", "templates/brokerage_template.html",
                "--session-id", "t1", "--out-dir", str(tmp_path / "out")])
    assert code == 1
    err = capsys.readouterr().err
    assert "No SuperDocs API key" in err
    assert "Traceback" not in err


def test_draft_validates_before_it_ever_looks_for_a_key(capsys, tmp_path, monkeypatch):
    """The blocking gate must fire first, so a refused pack reports the real
    reason rather than complaining about credentials."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    code = run(["draft", str(EXAMPLES / "incomplete_ca_unanswered.yaml"),
                "--template", "templates/brokerage_template.html",
                "--session-id", "t1", "--out-dir", str(tmp_path / "out")])
    assert code == 2
    assert "REFUSING TO DRAFT" not in capsys.readouterr().err


def test_check_returns_one_on_an_unreadable_record(capsys, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("pack_id: [unclosed\n", encoding="utf-8")
    assert run(["check", str(bad)]) == 1
    assert "Error:" in capsys.readouterr().err


def test_an_unknown_jurisdiction_exits_one_and_lists_the_known_ones(capsys):
    code = run(["check", str(EXAMPLES / "tx_austin_apartment.yaml"), "--jurisdiction", "US-ZZ"])
    assert code == 1
    assert "Known:" in capsys.readouterr().err


def test_preview_returns_two_rather_than_writing_a_refused_pack(capsys, tmp_path):
    out_dir = tmp_path / "out"
    assert run(["preview", str(EXAMPLES / "incomplete_ca_unanswered.yaml"),
                "--out-dir", str(out_dir)]) == 2
    assert not out_dir.exists() or not list(out_dir.glob("*.html"))


# ------------------------------------------------------------- offline promise


def test_preview_writes_three_documents_with_no_api_key(capsys, tmp_path, monkeypatch):
    """The whole offline path must work without a key present."""
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    out_dir = tmp_path / "out"
    assert run(["preview", str(EXAMPLES / "tx_austin_apartment.yaml"), "--out-dir", str(out_dir)]) == 0
    written = sorted(p.name for p in out_dir.glob("*.html"))
    assert written == [
        "TX-AUS-4412-compliance_index.html",
        "TX-AUS-4412-disclosure_packet.html",
        "TX-AUS-4412-lease.html",
    ]
    assert "Cross-document consistency: OK" in capsys.readouterr().out


def test_the_preview_html_is_self_contained_and_declares_utf8(tmp_path):
    out_dir = tmp_path / "out"
    run(["preview", str(EXAMPLES / "tx_austin_apartment.yaml"), "--out-dir", str(out_dir)])
    content = (out_dir / "TX-AUS-4412-lease.html").read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")
    assert "charset='utf-8'" in content
    assert "§" in content or "Tex. Prop. Code" in content


# --------------------------------------------------------------- the commands


def test_jurisdictions_lists_everything_shipped(capsys):
    assert run(["jurisdictions"]) == 0
    out = capsys.readouterr().out
    for code in ("US-CA", "US-TX", "US-NY", "US-FL", "US-FED"):
        assert code in out


def test_facts_marks_unanswered_questions(capsys):
    assert run(["facts", str(EXAMPLES / "incomplete_ca_unanswered.yaml")]) == 0
    out = capsys.readouterr().out
    assert "NOT SUPPLIED" in out
    assert "death_on_premises_last_3_years" in out
    assert "never read as 'does not apply'" in out


def test_facts_reports_a_complete_record_as_complete(capsys):
    assert run(["facts", str(EXAMPLES / "tx_austin_apartment.yaml")]) == 0
    assert "Every fact this jurisdiction asks about has an answer" in capsys.readouterr().out


def test_facts_labels_derived_values_so_nobody_types_them_in(capsys):
    assert run(["facts", str(EXAMPLES / "fl_tampa_condo.yaml")]) == 0
    assert "(derived)" in capsys.readouterr().out


def test_compare_shows_the_deposit_verdict_diverging(capsys):
    assert run(["compare", str(EXAMPLES / "compare_all_jurisdictions.yaml")]) == 0
    out = capsys.readouterr().out
    assert "OVER CAP — blocked" in out
    assert "within limits" in out
    assert "Required in exactly one of these jurisdictions" in out


def test_compare_names_the_uniquely_required_disclosures(capsys):
    run(["compare", str(EXAMPLES / "compare_all_jurisdictions.yaml")])
    out = capsys.readouterr().out
    assert "Radon Gas Disclosure  (US-FL only)" in out
    assert "Sprinkler System Notice  (US-NY only)" in out


def test_compare_accepts_a_subset_of_jurisdictions(capsys):
    assert run(["compare", str(EXAMPLES / "compare_all_jurisdictions.yaml"),
                "--jurisdictions", "US-TX,US-FL"]) == 0
    out = capsys.readouterr().out
    assert "US-TX" in out and "US-FL" in out and "US-NY" not in out


# ---------------------------------------------------------------- staleness UX


def test_today_lets_a_reviewer_see_the_pack_before_it_went_stale(capsys):
    """California blocks today on two fast-moving rules. Evaluated as of a date
    when they were current, it passes."""
    assert run(["check", str(EXAMPLES / "ca_oakland_apartment.yaml"), "--today", CURRENT]) == 0


def test_california_blocks_on_stale_rules_by_default(capsys):
    assert run(["check", str(EXAMPLES / "ca_oakland_apartment.yaml"), "--today", "2099-01-01"]) == 2
    assert "due for review by" in capsys.readouterr().out


def test_allow_stale_proceeds_and_says_it_will_mark_the_pack(capsys):
    assert run(["check", str(EXAMPLES / "ca_oakland_apartment.yaml"),
                "--today", "2099-01-01", "--allow-stale"]) == 0
    out = capsys.readouterr().out
    assert "PROCEEDING ANYWAY" in out and "UNVERIFIED" in out


def test_a_stale_pack_rendered_with_the_override_is_stamped_unverified(tmp_path):
    out_dir = tmp_path / "out"
    run(["preview", str(EXAMPLES / "ca_oakland_apartment.yaml"),
         "--out-dir", str(out_dir), "--today", "2099-01-01", "--allow-stale"])
    index = (out_dir / "CA-OAK-1187-compliance_index.html").read_text(encoding="utf-8")
    assert "UNVERIFIED — past review date" in index
    assert "UNVERIFIED items requiring re-check before use" in index


# ---------------------------------------------------- cross-jurisdiction check


def test_a_texas_record_run_against_new_york_rules_is_refused(capsys):
    """The clearest single demonstration that jurisdiction is not cosmetic: a
    perfectly valid Texas lease fails three different ways in New York."""
    assert run(["check", str(EXAMPLES / "tx_austin_apartment.yaml"),
                "--jurisdiction", "US-NY", "--today", CURRENT]) == 2
    out = capsys.readouterr().out
    assert "sprinkler_system_present" in out
    assert "exceeds the New York ceiling" in out


@pytest.mark.parametrize("example", sorted(p.name for p in EXAMPLES.glob("*.yaml")))
def test_every_shipped_example_either_passes_or_refuses_for_a_stated_reason(example, capsys):
    """No example may crash. Each must land on 0 or 2, never an unhandled error."""
    code = run(["check", str(EXAMPLES / example), "--allow-stale"])
    assert code in (0, 2), f"{example} exited {code}"
    if code == 2:
        assert "BLOCKING" in capsys.readouterr().out
