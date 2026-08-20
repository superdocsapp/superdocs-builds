import pytest

from adapter.profile import load_profile
from adapter.text import apply_text_rules

JA = load_profile("ja")
ZH = load_profile("zh-CN")
KO = load_profile("ko")
EN = load_profile("en", reverse=True)


def test_ja_comma_becomes_touten():
    out, stats = apply_text_rules("確認する, その後", JA)
    assert out == "確認する、 その後"
    assert stats["punctuation"]["count"] == 1


def test_ja_period_becomes_kuten_at_end():
    out, _ = apply_text_rules("Budget review on Tuesday.", JA)
    assert out == "Budget review on Tuesday。"


def test_ascii_comma_between_digits_kept():
    out, stats = apply_text_rules("Storage is 1,000 GB.", JA)
    assert "1,000" in out
    assert stats["punctuation"]["count"] == 1  # final period only


def test_period_between_latin_kept():
    out, stats = apply_text_rules("12 months. The next term.", JA)
    assert out == "12 months. The next term。"
    assert stats["punctuation"]["count"] == 1


def test_decimal_point_kept():
    out, _ = apply_text_rules("VAT is 8.25%.", JA)
    assert "8.25%" in out


def test_zh_comma_and_quotes():
    out, stats = apply_text_rules('他说"好", 然后离开。', ZH)
    assert out == "他说\u201c好\u201d， 然后离开。"
    assert stats["punctuation"]["count"] == 1
    assert stats["quotes"]["count"] == 2


def test_ko_keeps_ascii_punctuation():
    out, stats = apply_text_rules("확인, 그리고 계속.", KO)
    assert out == "확인, 그리고 계속."
    assert stats["punctuation"]["count"] == 0


def test_ja_quotes_become_corner_brackets():
    out, stats = apply_text_rules('the "Provider" said', JA)
    assert out == "the 「Provider」 said"
    assert stats["quotes"]["count"] == 2


def test_brackets_always_substituted():
    out, stats = apply_text_rules("(subject to renewal).", JA)
    assert out == "（subject to renewal）。"
    assert stats["punctuation"]["count"] == 3


def test_thin_space_inserted_between_cjk_and_latin():
    out, stats = apply_text_rules("日本語ABCテスト", JA)
    assert out == "日本語\u2009ABC\u2009テスト"
    assert stats["thin_spaces"]["count"] == 2


def test_thin_space_between_digit_and_cjk():
    out, _ = apply_text_rules("5人", JA)
    assert out == "5\u2009人"


def test_no_thin_space_around_dollar():
    out, _ = apply_text_rules("The fee is $59.", JA)
    assert out == "The fee is $59。"


def test_existing_space_boundary_becomes_thin():
    out, _ = apply_text_rules("10 GB ごとに", JA)
    assert out == "10 GB\u2009ごとに"


def test_kinsoku_attachment():
    out, stats = apply_text_rules("（ 内容 ）と「 語 」", JA)
    assert out == "（内容）と「語」"
    assert stats["kinsoku"]["count"] == 4


def test_reverse_punctuation_and_brackets():
    out, stats = apply_text_rules("（注）次にABC。", EN)
    assert out == "(注)次にABC."
    assert stats["punctuation"]["count"] >= 3


def test_reverse_removes_thin_spaces():
    out, stats = apply_text_rules("日本語\u2009ABC\u2009テスト", EN)
    assert out == "日本語ABCテスト"
    assert stats["thin_spaces"]["count"] == 2


def test_reverse_fullwidth_digits_and_letters():
    out, stats = apply_text_rules("１００件とＡＢＣ", EN)
    assert out == "100件とABC"
    assert stats["halfwidth"]["count"] == 6


def test_reverse_fullwidth_quotes():
    out, _ = apply_text_rules("「注」を読む", EN)
    assert out == "\"注\"を読む"


def test_stats_samples_capped():
    text = "文." * 20
    out, stats = apply_text_rules(text, JA)
    assert stats["punctuation"]["count"] == 20
    assert len(stats["punctuation"]["samples"]) <= 8


def test_ja_profile_geography():
    assert JA.lang == "ja"
    assert JA.body_size_pt == 10.5
    assert JA.page["margin_top_mm"] == 25


def test_zh_profile_geography():
    assert ZH.page["margin_top_mm"] == 37
    assert ZH.page["margin_left_mm"] == 28


def test_unknown_locale_raises():
    with pytest.raises(ValueError):
        load_profile("fr")
