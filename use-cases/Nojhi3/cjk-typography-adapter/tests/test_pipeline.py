import json
import re
from pathlib import Path

import pytest

from adapter.cli import main
from adapter.htmltree import collect_blocks, parse_html, serialize
from adapter.pipeline import adapt

PROJECT = Path(__file__).parent.parent
SAMPLE_HTML = PROJECT / "data" / "sample" / "sample.html"
SAMPLE_MD = PROJECT / "data" / "sample" / "sample.md"

# Hand-computed expected rule counts for data/sample/sample.html under the ja profile.
EXPECTED_JA = {"punctuation": 25, "quotes": 8, "thin_spaces": 3, "kinsoku": 2, "halfwidth": 0}


def _checklist_counts(out_dir):
    data = json.loads((out_dir / "checklist.json").read_text(encoding="utf-8"))
    return {k: v["count"] for k, v in data["rules"].items()}


def _target_char_counts(html_text, original_text):
    def scan(text):
        return {
            "punctuation": sum(text.count(c) for c in "、。！？：；（）"),
            "quotes": sum(text.count(c) for c in "「」"),
            "thin_spaces": text.count("\u2009"),
        }

    after, before = scan(html_text), scan(original_text)
    return {k: after[k] - before[k] for k in after}


def test_adapt_html_outputs_exist(tmp_path):
    result = adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path)
    assert result.out_html.exists()
    assert result.out_docx.exists()
    assert result.comparison_html.exists()
    assert result.checklist_json.exists()
    assert result.checklist_md.exists()
    assert result.out_html.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


def test_checklist_matches_hand_computed_counts(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path)
    assert _checklist_counts(tmp_path) == EXPECTED_JA


def test_checklist_matches_actual_changes_md(tmp_path):
    adapt(SAMPLE_MD, locale="ja", out_dir=tmp_path)
    adapted = (tmp_path / "adapted.html").read_text(encoding="utf-8")
    original = SAMPLE_MD.read_text(encoding="utf-8")
    counts = _checklist_counts(tmp_path)
    actual = _target_char_counts(adapted, original)
    assert counts["punctuation"] == actual["punctuation"]
    assert counts["quotes"] == actual["quotes"]
    assert counts["thin_spaces"] == actual["thin_spaces"]


def test_adapted_content(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path)
    html_text = (tmp_path / "adapted.html").read_text(encoding="utf-8")
    assert 'lang="ja"' in html_text
    assert "（subject to annual renewal）。" in html_text
    assert "included。 超過分は" in html_text
    assert "「the Provider」" in html_text
    assert "10 GB\u2009ごとに" in html_text
    assert "備考（別紙参照）。" in html_text
    assert "@page" in html_text
    assert "Terms &amp; conditions" in html_text


def test_comparison_contains_both_versions(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path)
    comp = (tmp_path / "comparison.html").read_text(encoding="utf-8")
    assert "Northwind Corp" in comp
    assert "subject to annual renewal" in comp
    assert "chg-ins" in comp


def test_checklist_md_structure(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path)
    md = (tmp_path / "checklist.md").read_text(encoding="utf-8")
    assert "## Page geometry" in md
    assert "## Rules applied" in md
    assert "Punctuation substitution" in md
    assert "## CSS emitted" in md


def test_zh_profile_pipeline(tmp_path):
    adapt(SAMPLE_HTML, locale="zh-CN", out_dir=tmp_path)
    html_text = (tmp_path / "adapted.html").read_text(encoding="utf-8")
    assert 'lang="zh-CN"' in html_text
    assert "（subject to annual renewal）。" in html_text
    assert "margin: 37mm 26mm 35mm 28mm" in html_text


def test_ko_keeps_ascii_punct(tmp_path):
    adapt(SAMPLE_HTML, locale="ko", out_dir=tmp_path)
    html_text = (tmp_path / "adapted.html").read_text(encoding="utf-8")
    assert 'lang="ko"' in html_text
    assert "（subject to annual renewal）。" not in html_text
    assert "10 GB ごとに" not in html_text


def test_reverse_direction(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path / "ja")
    adapt(tmp_path / "ja" / "adapted.html", locale="ja", reverse=True, out_dir=tmp_path / "en")
    data = json.loads((tmp_path / "en" / "checklist.json").read_text(encoding="utf-8"))
    assert data["direction"] == "cjk-to-latin"
    html_text = (tmp_path / "en" / "adapted.html").read_text(encoding="utf-8")
    assert 'lang="en"' in html_text
    assert "@page" in html_text
    assert "margin: 25mm 25mm 25mm 25mm" in html_text


def test_reverse_round_trip_reconstructs_original(tmp_path):
    adapt(SAMPLE_HTML, locale="ja", out_dir=tmp_path / "ja")
    adapt(tmp_path / "ja" / "adapted.html", locale="ja", reverse=True, out_dir=tmp_path / "en")
    original = collect_blocks(parse_html(SAMPLE_HTML.read_text(encoding="utf-8")))
    round_trip = collect_blocks(parse_html((tmp_path / "en" / "adapted.html").read_text(encoding="utf-8")))
    assert len(original) == len(round_trip)

    def normalize(text):
        for src, dst in (("（", "("), ("）", ")"), ("。", "."), ("、", ","), ("，", ","),
                         ("「", '"'), ("」", '"'), ("\u3000", " ")):
            text = text.replace(src, dst)
        return re.sub(r"\s+", "", text)

    for a, b in zip(original, round_trip):
        assert normalize(a) == normalize(b)


def test_cli_smoke(tmp_path, capsys):
    rc = main([str(SAMPLE_HTML), "--locale", "ja", "--out-dir", str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Adapted" in captured
    assert "punctuation=25" in captured
    assert (tmp_path / "adapted.docx").exists()


def test_cli_bad_locale(tmp_path, capsys):
    rc = main([str(SAMPLE_HTML), "--locale", "xx", "--out-dir", str(tmp_path)])
    assert rc == 2
