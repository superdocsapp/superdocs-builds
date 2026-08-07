"""The two things that must never go wrong: money and keys.

Money: an operation is never spent without a durable ledger line, and the cap
is enforced BEFORE the call, not after.

Keys: nothing key-shaped reaches a log, a fixture or a commit.
"""

import json
import os

import pytest

from superdocs_kit.budget import OpsBudget
from superdocs_kit.errors import BudgetExceeded, QuotaExhausted
from superdocs_kit.secrets import redact

RESPONSE = {"usage": {"ops_charged": 1, "monthly_used": 7, "was_billable": True}}


def test_cost_comes_from_the_server_not_from_a_guess(tmp_path):
    b = OpsBudget(tmp_path / "l.jsonl", max_ops=10)
    assert b.record("w01", {"usage": {"ops_charged": 3, "monthly_used": 3}}, 1.0) == 3
    assert b.spent == 3


def test_cap_is_checked_before_spending(tmp_path):
    b = OpsBudget(tmp_path / "l.jsonl", max_ops=2)
    b.record("w01", RESPONSE, 1.0)
    b.record("w02", RESPONSE, 1.0)
    with pytest.raises(BudgetExceeded) as exc:
        b.check("w03")
    assert "fix:" in str(exc.value), "an error must name the fix, not just the cause"


def test_reserve_protects_headroom(tmp_path):
    b = OpsBudget(tmp_path / "l.jsonl", max_ops=10, reserve=8)
    b.record("w01", RESPONSE, 1.0)
    assert b.remaining == 1
    with pytest.raises(BudgetExceeded):
        b.check("w02", expected=2)


def test_ledger_survives_a_restart(tmp_path):
    path = tmp_path / "l.jsonl"
    first = OpsBudget(path, max_ops=10)
    first.record("w01", RESPONSE, 1.0)
    first.record("w02", RESPONSE, 2.0)
    # a fresh process reading the same file must see the same spend
    second = OpsBudget(path, max_ops=10)
    assert second.spent == 2
    assert second.already_done("w01") and not second.already_done("w99")


def test_every_charge_is_flushed_immediately(tmp_path):
    """A kill -9 between two weeks must not lose the record of what was paid."""
    path = tmp_path / "l.jsonl"
    b = OpsBudget(path, max_ops=10)
    b.record("w01", RESPONSE, 1.0)
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    assert lines and lines[0]["label"] == "w01" and lines[0]["ops"] == 1


def test_quota_exhausted_is_recorded_then_raised(tmp_path):
    path = tmp_path / "l.jsonl"
    b = OpsBudget(path, max_ops=100)
    with pytest.raises(QuotaExhausted):
        b.record("w01", {"usage": {"ops_charged": 1, "quota_exhausted": True}}, 1.0)
    assert path.read_text().strip(), "the spend must be on the ledger before we raise"


def test_free_calls_are_timed_but_not_charged(tmp_path):
    b = OpsBudget(tmp_path / "l.jsonl", max_ops=5)
    b.record_free("export", 0.4)
    assert b.spent == 0 and b.summary()["calls"] == 1


def test_summary_reports_what_a_reader_needs(tmp_path):
    b = OpsBudget(tmp_path / "l.jsonl", max_ops=5)
    b.record("w01", RESPONSE, 1.5)
    s = b.summary()
    assert s["ops_spent"] == 1 and s["remaining"] == 4 and s["wall_seconds"] == 1.5


# ---------------------------------------------------------------- secrets
@pytest.mark.parametrize("text,expected_absent", [
    ("Authorization: Bearer sk_0000000000000000000000000000fake", "0000000000"),
    ("key is sk_abcdef0123456789 ok", "abcdef0123456789"),
    ("curl -H 'Authorization: Bearer tok_averylongtokenvalue123'", "averylongtokenvalue123"),
])
def test_redact_removes_credentials_from_strings(text, expected_absent):
    assert expected_absent not in redact(text)


def test_redact_walks_nested_structures():
    payload = {
        "headers": {"Authorization": "Bearer sk_deadbeefdeadbeefdeadbeef"},
        "body": {"message": "use sk_cafebabecafebabecafebabe please"},
        "list": ["sk_0123456789abcdef0123", {"api_key": "sk_zzzzzzzzzzzzzzzzzzzz"}],
    }
    blob = json.dumps(redact(payload))
    for leak in ("deadbeef", "cafebabe", "0123456789abcdef", "zzzzzzzzzzzz"):
        assert leak not in blob


def test_redact_leaves_ordinary_text_alone():
    assert redact("the section on risks") == "the section on risks"


def test_env_does_not_override_a_real_environment_variable(tmp_path, monkeypatch):
    from superdocs_kit.secrets import load_env

    monkeypatch.setenv("SUPERDOCS_API_KEY", "from-environment")
    (tmp_path / ".env").write_text("SUPERDOCS_API_KEY=from-file\n")
    load_env(tmp_path / "anything.py")
    assert os.environ["SUPERDOCS_API_KEY"] == "from-environment"


def test_missing_key_error_names_the_fix(monkeypatch):
    from superdocs_kit.errors import AuthError
    from superdocs_kit.secrets import api_key

    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    monkeypatch.setattr("superdocs_kit.secrets.load_env", lambda *a, **k: None)
    with pytest.raises(AuthError) as exc:
        api_key()
    assert "replay" in str(exc.value).lower() or ".env" in str(exc.value)
