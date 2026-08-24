"""Runs vectors.json — the same file the TypeScript implementation runs.

If these two suites ever disagree, the specification is ambiguous and SPEC.md
is what gets fixed, not whichever implementation is more convenient.
"""

from __future__ import annotations

import pytest

from idem import OutcomeUnknown, RetriesExhausted, TerminalFailure
from tests.vectorlib import (
    UNKNOWN_POLICIES,
    ScriptedOperation,
    build,
    load_policy,
    load_vectors,
    probe_returning,
)

RAISES = {
    "OutcomeUnknown": OutcomeUnknown,
    "TerminalFailure": TerminalFailure,
    "RetriesExhausted": RetriesExhausted,
}

VECTORS = load_vectors()


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vector(vector, tmp_path):
    policy = load_policy()
    idem, delays_ms = build(tmp_path, policy)
    operation = ScriptedOperation(vector["attempts"])
    probe = probe_returning(vector)
    key = vector["id"]

    for n, invocation in enumerate(vector["invocations"]):
        expect = invocation["expect"]
        call = lambda: idem.run(  # noqa: E731 - bound per iteration on purpose
            key,
            operation,
            on_unknown=UNKNOWN_POLICIES[invocation.get("on_unknown", "refuse")],
            probe=probe,
            naturally_idempotent=invocation.get("naturally_idempotent", False),
        )
        if expect.get("raised"):
            with pytest.raises(RAISES[expect["raised"]]):
                call()
        else:
            assert call() == expect.get("result"), f"invocation {n} returned the wrong result"

    final = vector["expect"]

    # The assertion that matters: how many times the operation actually ran.
    assert operation.executions == final["executions"], "wrong number of executions"
    assert idem.store.state_of(key) == final["final_state"]
    assert len(delays_ms) == final["delay_count"], f"delays were {delays_ms}"

    if final.get("delays_exact_ms"):
        assert delays_ms == pytest.approx(final["delays_exact_ms"])

    if final.get("assert_delay_bounds"):
        # By bound, never by value: seeded RNGs are not portable across
        # languages, so pinning exact delays would pin an implementation
        # detail rather than the specified behaviour (SPEC.md R11).
        for n, delay in enumerate(delays_ms):
            ceiling = policy.backoff.ceiling_ms(n)
            assert 0.0 <= delay <= ceiling, f"delay {n} = {delay}ms exceeds ceiling {ceiling}ms"


def test_every_vector_names_a_requirement():
    for vector in VECTORS:
        assert vector.get("requirement", "").startswith("R"), vector["id"]
        assert vector.get("why"), f"{vector['id']} does not say why it exists"


def test_the_script_is_fully_consumed():
    """A vector that scripts attempts the run never reaches is a vector that
    is not testing what it claims to test."""
    for vector in VECTORS:
        scripted = len(vector["attempts"])
        assert scripted == vector["expect"]["executions"], (
            f"{vector['id']}: scripts {scripted} attempts but expects "
            f"{vector['expect']['executions']} executions"
        )
