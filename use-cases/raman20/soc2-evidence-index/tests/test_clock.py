import os

from soc2_index.clock import generated_at


def test_source_date_epoch(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert generated_at() == "1970-01-01T00:00:00Z"


def test_override_wins(monkeypatch):
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    assert generated_at("2025-01-02T00:00:00Z") == "2025-01-02T00:00:00Z"
