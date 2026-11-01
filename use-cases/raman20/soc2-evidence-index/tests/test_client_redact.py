from soc2_index.logutil import JsonlLogger, redact, redact_headers


def test_redact_authorization(tmp_path):
    log = JsonlLogger(tmp_path / "log.jsonl")
    log.log("http", headers=redact_headers({"Authorization": "Bearer sk_" + "ab" * 16}))
    text = (tmp_path / "log.jsonl").read_text()
    assert "Authorization" in text or "headers" in text
    assert "sk_abab" not in text
    assert "[redacted]" in text


def test_redact_key_in_message():
    s = redact("token sk_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa extra")
    assert "sk_aaaa" not in s
