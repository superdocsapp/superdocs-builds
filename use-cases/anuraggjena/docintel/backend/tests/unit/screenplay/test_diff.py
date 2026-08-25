from backend.modules.screenplay.diff import compute_diff_tokens


def test_no_change():
    tokens = compute_diff_tokens("INT. OFFICE - DAY", "INT. OFFICE - DAY")
    assert all(t["type"] == "equal" for t in tokens)


def test_capitalization_diff():
    tokens = compute_diff_tokens("int. office - day", "INT. OFFICE - DAY")
    types = {t["type"] for t in tokens}
    assert "delete" in types or "replace" in types or "insert" in types


def test_empty_strings():
    tokens = compute_diff_tokens("", "")
    assert tokens == []


def test_tokens_are_dicts_with_type_and_text():
    tokens = compute_diff_tokens("hello", "HELLO")
    for t in tokens:
        assert "type" in t
        assert "text" in t
        assert t["type"] in ("equal", "insert", "delete", "replace")
