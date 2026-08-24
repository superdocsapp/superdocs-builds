"""The nevers from SPEC.md section 1, one test each.

These were written before the code they check. A retry library that is merely
usually correct is worse than none at all: it turns a visible failure into an
invisible one.
"""

from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

import pytest

from idem import (
    Idempotent,
    OutcomeUnknown,
    Policy,
    RetriesExhausted,
    TerminalFailure,
    UnknownPolicy,
    Verdict,
)
from tests.vectorlib import POLICY_PATH, ScriptedError, ScriptedOperation, build

SOURCE_DIR = Path(__file__).resolve().parents[1] / "idem"


def _err(name, **kw):
    return type(name, (ScriptedError,), {})(name, **kw)


# ---- N1: never execute the same operation key twice -------------------------


def test_completed_key_replays_recorded_result(tmp_path):
    idem, _ = build(tmp_path)
    calls = []

    def operation():
        calls.append(1)
        return {"job_id": "j-1", "applied": True}

    first = idem.run("edit-para-7", operation)
    second = idem.run("edit-para-7", operation)
    third = idem.run("edit-para-7", lambda: pytest.fail("must not execute"))

    assert first == second == third
    assert len(calls) == 1, "the operation ran more than once for one key"


def test_a_second_key_is_a_second_operation(tmp_path):
    """The guard is the key, not the function. Two keys mean two operations,
    which is what makes the caller responsible for naming them stably (R1)."""
    idem, _ = build(tmp_path)
    calls = []
    op = lambda: (calls.append(1), {"job_id": f"j-{len(calls)}"})[1]  # noqa: E731

    idem.run("edit-para-7", op)
    idem.run("edit-para-8", op)
    assert len(calls) == 2


# ---- N2: never retry an unknown outcome without an explicit policy ----------


def test_unknown_refuses_by_default(tmp_path):
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown):
        idem.run("timed-out", op)

    assert op.executions == 1
    assert idem.store.state_of("timed-out") == "unknown"


def test_refusal_persists_across_repeated_calls(tmp_path):
    """Resubmitting the same key does not wear the refusal down. Without this,
    a caller in a retry loop of its own gets the double-apply anyway."""
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    for _ in range(5):
        with pytest.raises(OutcomeUnknown):
            idem.run("timed-out", op)

    assert op.executions == 1


def test_retry_anyway_needs_the_caller_to_vouch(tmp_path):
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown, match="naturally_idempotent"):
        idem.run("timed-out", op, on_unknown=UnknownPolicy.RETRY_ANYWAY)

    assert op.executions == 1


# ---- N3: never report a success it did not observe --------------------------


@pytest.mark.parametrize(
    "failure,expected_error,expected_state",
    [
        ({"event": "error", "class": "ReadTimeout", "sent": True}, OutcomeUnknown, "unknown"),
        ({"event": "error", "class": "X", "status": 503, "sent": True}, OutcomeUnknown, "unknown"),
        ({"event": "error", "class": "X", "status": 409, "sent": True}, TerminalFailure, "failed"),
        ({"event": "error", "class": "X", "status": 422, "sent": True}, TerminalFailure, "failed"),
        ({"event": "error", "class": "Nobody", "sent": True}, OutcomeUnknown, "unknown"),
    ],
)
def test_never_synthesises_success(tmp_path, failure, expected_error, expected_state):
    """No failure path may end in a success state or hand back a result."""
    idem, _ = build(tmp_path)
    op = ScriptedOperation([failure])

    with pytest.raises(expected_error):
        idem.run("k", op)

    assert idem.store.state_of("k") == expected_state
    assert idem.store.get("k").result is None


def test_inconclusive_reconciliation_is_not_a_success(tmp_path):
    """The dangerous shape: asking the server, learning nothing, and treating
    the absence of bad news as good news."""
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown):
        idem.run("k", op, on_unknown=UnknownPolicy.RECONCILE,
                 probe=lambda _rec: Verdict.INCONCLUSIVE)

    assert idem.store.state_of("k") == "unknown"
    assert op.executions == 1


def test_reconcile_without_a_job_id_or_a_probe_is_inconclusive(tmp_path):
    """SPEC.md section 6, the documented limit. The first call timed out, so no
    job id was ever bound and the server cannot be asked. 'I could not find
    out' must not become 'it did not happen'."""
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown):
        idem.run("k", op)

    assert idem.reconcile("k") is Verdict.INCONCLUSIVE
    assert idem.store.state_of("k") == "unknown"


# ---- N5: never retry a failure the table marks terminal ---------------------


def test_terminal_is_not_retried(tmp_path):
    idem, delays = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "X", "status": 409, "sent": True}])

    with pytest.raises(TerminalFailure):
        idem.run("wedged", op)

    assert op.executions == 1, "a terminal failure was retried"
    assert delays == [], "the library backed off before a failure it should not retry"


def test_terminal_record_refuses_without_executing(tmp_path):
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "X", "status": 409, "sent": True}])

    with pytest.raises(TerminalFailure):
        idem.run("wedged", op)
    with pytest.raises(TerminalFailure):
        idem.run("wedged", lambda: pytest.fail("must not execute"))

    assert op.executions == 1


def test_exhaustion_releases_the_key_but_terminal_does_not(tmp_path):
    """Retryable means provably not applied, so the key goes back. Terminal
    means the server gave an answer, so it stays (SPEC.md R10)."""
    idem, _ = build(tmp_path)

    exhausted = ScriptedOperation(
        [{"event": "error", "class": "ConnectTimeout", "sent": False}] * 5
    )
    with pytest.raises(RetriesExhausted):
        idem.run("flaky", exhausted)
    assert idem.store.state_of("flaky") == "new"

    terminal = ScriptedOperation([{"event": "error", "class": "X", "status": 409, "sent": True}])
    with pytest.raises(TerminalFailure):
        idem.run("wedged", terminal)
    assert idem.store.state_of("wedged") == "failed"


# ---- R1: the library never invents a key ------------------------------------


def test_library_never_generates_a_key(tmp_path):
    idem, _ = build(tmp_path)
    idem.run("mine-1", lambda: {"job_id": "a"})
    idem.run("mine-2", lambda: {"job_id": "b"})

    with idem.store._connect() as conn:
        stored = {row[0] for row in conn.execute("SELECT key FROM operations")}
    assert stored == {"mine-1", "mine-2"}

    for source in SOURCE_DIR.glob("*.py"):
        text = source.read_text()
        assert "import uuid" not in text, f"{source.name} can generate identifiers"
        assert "uuid4" not in text, f"{source.name} can generate identifiers"


# ---- R7: the policy is data, not conditionals -------------------------------


def test_policy_is_data_not_conditionals():
    """The card asks for policy as data rather than conditionals scattered
    through the code. That is checkable, so it is checked.

    The runner branches on the four abstract outcomes the table returns. It
    must never branch on an HTTP status code or an error class name — the
    mapping from observation to outcome belongs entirely in policy.json.
    """
    raw = json.loads(POLICY_PATH.read_text())
    error_names = {
        rule["when"]["error"] for rule in raw["rules"] if "error" in rule["when"]
    }
    assert error_names, "the table names no error classes, so this test proves nothing"

    statuses = re.compile(r"\b[2-5]\d\d\b")
    for source in (SOURCE_DIR / "runner.py", SOURCE_DIR / "policy.py"):
        code = "\n".join(
            line.split("#")[0] for line in source.read_text().splitlines()
        )
        found = statuses.findall(code)
        assert not found, f"{source.name} contains status-code literals: {found}"
        for name in error_names:
            assert name not in code, f"{source.name} names the error class {name!r}"


def test_the_table_refuses_to_load_an_undocumented_decision(tmp_path):
    """Every non-success rule must carry its reasoning. A rule that classifies
    a failure without saying why is the thing this build replaces, so the
    loader rejects it rather than trusting review to catch it."""
    raw = json.loads(POLICY_PATH.read_text())
    for rule in raw["rules"]:
        if rule["id"] == "conflict":
            del rule["why"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(Exception, match="why"):
        Policy.load(path)


def test_the_table_refuses_to_load_without_a_catch_all(tmp_path):
    raw = json.loads(POLICY_PATH.read_text())
    raw["rules"] = [r for r in raw["rules"] if r["when"] != {}]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw))

    with pytest.raises(Exception, match="catch-all"):
        Policy.load(path)


def test_an_unattested_failure_is_assumed_sent(tmp_path):
    """A bare exception carries no 'sent' attribute. Assuming it never left the
    client would make it retryable, and that assumption is exactly how a metered
    edit gets applied twice."""
    idem, _ = build(tmp_path)
    calls = []

    def operation():
        calls.append(1)
        raise RuntimeError("something went wrong and said nothing useful")

    with pytest.raises(OutcomeUnknown):
        idem.run("bare", operation)

    assert len(calls) == 1


# ---- R11: the backoff is actually jittered ----------------------------------
#
# Found by mutation testing, not by design. The behavioural vectors assert
# 0 <= delay <= ceiling, and a constant delay == ceiling satisfies that — so
# deleting the jitter entirely left the whole suite green. The card asks for
# jittered backoff specifically, and "within bounds" does not mean "jittered".
#
# The fix is a distribution test rather than a value test, so it stays portable
# across languages: the vectors still cannot pin an RNG, but they can pin the
# shape it must produce.


def _sample_delays(n=400, attempt=3):
    policy = Policy.load(POLICY_PATH)
    rng = random.Random(20260823)
    return [policy.backoff.delay_ms(attempt, rng) for _ in range(n)], \
        policy.backoff.ceiling_ms(attempt)


def test_backoff_is_not_a_constant():
    """The mutation that got through: return the ceiling every time. Under full
    jitter 400 draws are essentially all distinct; a constant scores 1."""
    delays, _ = _sample_delays()
    assert len(set(delays)) > 200, "the backoff is not varying — the jitter is gone"


def test_backoff_spreads_across_its_whole_range():
    """Full jitter draws from [0, ceiling]. Equal jitter (ceiling/2 + rand) and
    decorrelated jitter both keep a floor under the delay, which re-synchronises
    clients that failed together — so the low end of the range must be reachable.

    P(no draw below 10% of the ceiling in 400 samples) = 0.9**400 ≈ 1e-18.
    """
    delays, ceiling = _sample_delays()
    assert min(delays) < ceiling * 0.10, (
        f"nothing was drawn below {ceiling * 0.10:.0f}ms — this is not full jitter"
    )
    assert max(delays) <= ceiling
    assert max(delays) > ceiling * 0.90, "the top of the range is never reached"


def test_backoff_mean_matches_full_jitter():
    """Uniform(0, C) has mean C/2 and sd C/sqrt(12). Over 400 draws the standard
    error is about 0.014C, so a band of +/-8% is roughly six sigma: tight enough
    to reject a different jitter strategy, wide enough never to flake."""
    delays, ceiling = _sample_delays()
    mean = sum(delays) / len(delays)
    assert 0.42 * ceiling < mean < 0.58 * ceiling, (
        f"mean delay {mean:.0f}ms is not half of the {ceiling:.0f}ms ceiling; "
        f"this is not full jitter"
    )


# ---- N3: a NOT_APPLIED verdict is not a success -----------------------------
#
# Mutation testing caught this suite catching it only by accident: making
# reconcile() treat every non-inconclusive verdict as APPLIED was detected
# incidentally, and stopped being detected the moment an unrelated control-flow
# fix landed. An incidental catch is not a test. This is the explicit one, and
# it mirrors the TypeScript suite exactly.


def test_not_applied_releases_the_key_it_does_not_succeed_it(tmp_path):
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown):
        idem.run("k", op)
    assert idem.store.state_of("k") == "unknown"

    verdict = idem.reconcile("k", probe=lambda _rec: Verdict.NOT_APPLIED)

    assert verdict is Verdict.NOT_APPLIED
    assert idem.store.state_of("k") == "new", "NOT_APPLIED must release the key"
    assert idem.store.state_of("k") != "succeeded", "the library invented a success"


@pytest.mark.parametrize(
    "verdict,expected_state",
    [
        (Verdict.APPLIED, "succeeded"),
        (Verdict.NOT_APPLIED, "new"),
        (Verdict.INCONCLUSIVE, "unknown"),
    ],
)
def test_only_applied_may_produce_a_succeeded_record(tmp_path, verdict, expected_state):
    idem, _ = build(tmp_path)
    op = ScriptedOperation([{"event": "error", "class": "ReadTimeout", "sent": True}])

    with pytest.raises(OutcomeUnknown):
        idem.run("k", op)

    idem.reconcile("k", probe=lambda _rec: verdict)
    assert idem.store.state_of("k") == expected_state


# ---- resource discipline ----------------------------------------------------


def test_the_store_does_not_leak_file_descriptors(tmp_path):
    """`with sqlite3.connect(...) as conn` commits; it does not close. With a
    connection per call that leaked one descriptor per store operation — 335
    over 200 runs — until the process hit its limit and every further open
    failed with "unable to open database file".

    Found by the fuzzer, which was the first thing to run enough operations to
    exhaust the limit. A defect in the library, not in the test: any
    long-running caller would have died the same way.
    """
    idem, _ = build(tmp_path)
    open_fds = lambda: len(os.listdir("/dev/fd"))  # noqa: E731

    idem.run("warmup", lambda: {"job_id": "j"})
    before = open_fds()

    for n in range(300):
        idem.run(f"key-{n}", lambda: {"job_id": "j"})

    after = open_fds()
    assert after - before <= 2, (
        f"leaked {after - before} file descriptors over 300 operations "
        f"({before} -> {after})"
    )
