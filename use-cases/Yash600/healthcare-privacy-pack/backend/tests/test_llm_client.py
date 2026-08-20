"""
test_llm_client.py -- regression tests for the Groq TPM-budget batching
fix in llm_client.py.

Context: a real Analyze References run on a large policy/procedure pair
hit a live Groq 413 rate_limit_exceeded (Requested 19615 tokens vs the
free-tier TPM Limit of 8000) once max_tokens was raised to fix a separate,
also-live 400 tool_use_failed truncation bug. Both bugs were real and both
fixes have to hold at once: max_tokens needs to be big enough that a long
relationships array doesn't get cut off mid-object, AND the total request
(prompt + max_tokens) needs to stay under the free-tier ceiling. The fix
is to batch the procedure side of the request rather than raise/lower a
single number -- these tests exist to prove that actually happens rather
than just trusting the arithmetic in llm_client.py.

No live Groq key is used anywhere here: discover_references' HTTP call is
monkeypatched at the requests.Session level, same pattern the rest of the
suite uses for SuperDocs (see tests/fakes.py).
"""

from __future__ import annotations

import json

import pytest

import llm_client
from llm_client import (
    GROQ_FREE_TPM_LIMIT,
    LLMClient,
    SectionInput,
    _EFFECTIVE_TPM_BUDGET,
    _MAX_TOKENS_PER_BATCH,
    _estimate_tokens,
    _plan_batches,
    _render_procedure_block,
)


def _section(idx: int, content_chars: int) -> SectionInput:
    return SectionInput(
        id=f"sec-{idx}",
        number=str(idx),
        title=f"Section {idx}",
        content_text="lorem ipsum dolor sit amet " * (content_chars // 28 + 1),
    )


# -- _plan_batches / _estimate_tokens ------------------------------------


def test_plan_batches_keeps_small_request_in_one_batch():
    policy = [_section(1, 400)]
    procedure = [_section(i, 400) for i in range(1, 4)]
    batches = _plan_batches("Policy", policy, "Procedure", procedure)
    assert len(batches) == 1
    assert [s.id for s in batches[0]] == [s.id for s in procedure]


def test_plan_batches_splits_large_procedure_set_under_tpm_budget():
    # A small policy, but a procedure with many meaty sections -- enough
    # combined content that one request would have exceeded Groq's free
    # 8000 TPM ceiling in practice (this is what actually happened live).
    policy = [_section(1, 500)]
    procedure = [_section(i, 3000) for i in range(1, 11)]  # 10 large sections

    batches = _plan_batches("Policy", policy, "Procedure", procedure)

    assert len(batches) > 1, "a large procedure set must be split, not sent in one call"

    # Every procedure section must appear exactly once across all batches --
    # batching must not drop or duplicate sections.
    all_ids = [s.id for batch in batches for s in batch]
    assert all_ids == [s.id for s in procedure]

    # The contract batching exists to uphold: each batch's own prompt
    # (full policy + just that batch) plus the fixed output budget must
    # stay under the free-tier ceiling, with the safety margin honored.
    for batch in batches:
        prompt = llm_client._build_prompt("Policy", policy, "Procedure", batch)
        estimated_request_tokens = _estimate_tokens(prompt) + _MAX_TOKENS_PER_BATCH
        assert estimated_request_tokens <= _EFFECTIVE_TPM_BUDGET
        assert estimated_request_tokens <= GROQ_FREE_TPM_LIMIT


def test_plan_batches_degenerate_huge_policy_still_makes_progress():
    # Pathological case: even the policy alone eats most of the budget.
    # Batching can't shrink the policy (every batch needs full policy
    # context), so the best it can do is one procedure section per batch --
    # but it must never silently drop a section or infinite-loop.
    policy = [_section(1, 30000)]
    procedure = [_section(i, 500) for i in range(1, 4)]

    batches = _plan_batches("Policy", policy, "Procedure", procedure)

    assert len(batches) == 3  # one section per batch, degenerate but correct
    all_ids = [s.id for batch in batches for s in batch]
    assert all_ids == [s.id for s in procedure]


def test_estimate_tokens_is_a_positive_monotonic_heuristic():
    assert _estimate_tokens("") >= 1
    assert _estimate_tokens("a" * 400) > _estimate_tokens("a" * 40)


# -- discover_references (mocked HTTP) ------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _groq_response_for(procedure_ids: list[str], reason: str) -> _FakeResponse:
    """Builds a Groq-shaped response echoing back one relationship per
    procedure id it was given, so a test can verify which batch produced
    which relationship after they're all merged."""
    relationships = [
        {
            "procedure_section_id": pid,
            "policy_section_id": "sec-1",
            "confidence": 0.9,
            "reason": reason,
        }
        for pid in procedure_ids
    ]
    return _FakeResponse(
        {
            "model": "openai/gpt-oss-120b",
            "usage": {"prompt_tokens": 111, "completion_tokens": 22},
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "report_references",
                                    "arguments": json.dumps({"relationships": relationships}),
                                }
                            }
                        ]
                    }
                }
            ],
        }
    )


def test_discover_references_makes_one_call_for_small_pair(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = LLMClient()

    calls = []

    def fake_post(url, json, timeout):  # noqa: A002 -- matches requests.Session.post's kwarg name
        calls.append(json)
        procedure_ids = [
            line.split("]")[0][1:].split("=")[1]
            for line in json["messages"][0]["content"].splitlines()
            if line.startswith("[id=")
        ]
        # only the procedure ids (not the policy id) should drive the response
        procedure_ids = [pid for pid in procedure_ids if pid != "sec-1"]
        return _groq_response_for(procedure_ids, "single batch")

    monkeypatch.setattr(client._session, "post", fake_post)

    policy = [_section(1, 300)]
    procedure = [_section(2, 300), _section(3, 300)]
    result = client.discover_references("Policy", policy, "Procedure", procedure)

    assert len(calls) == 1
    assert {r.procedure_section_id for r in result.relationships} == {"sec-2", "sec-3"}
    assert result.usage.input_tokens == 111
    assert result.usage.output_tokens == 22


def test_discover_references_batches_and_merges_large_pair(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = LLMClient()

    calls = []

    def fake_post(url, json, timeout):  # noqa: A002
        calls.append(json)
        content = json["messages"][0]["content"]
        all_ids = [
            line.split("]")[0][1:].split("=")[1]
            for line in content.splitlines()
            if line.startswith("[id=")
        ]
        # drop the policy section's own id (sec-1), which is present in every batch
        procedure_ids = [pid for pid in all_ids if pid != "sec-1"]
        # every request must actually respect the per-batch max_tokens budget
        assert json["max_tokens"] == _MAX_TOKENS_PER_BATCH
        # and must cap reasoning-token generation -- gpt-oss-120b otherwise
        # spends part of max_tokens on hidden <reasoning> before the tool
        # call, which is what caused a live 400 tool_use_failed truncation
        # even though the visible JSON was well under budget.
        assert json["reasoning_effort"] == "low"
        assert json["include_reasoning"] is False
        return _groq_response_for(procedure_ids, f"batch of {len(procedure_ids)}")

    monkeypatch.setattr(client._session, "post", fake_post)

    policy = [_section(1, 500)]
    procedure = [_section(i, 3000) for i in range(2, 12)]  # 10 large sections
    result = client.discover_references("Policy", policy, "Procedure", procedure)

    assert len(calls) > 1, "large pair must trigger more than one Groq call"

    got_ids = {r.procedure_section_id for r in result.relationships}
    expected_ids = {s.id for s in procedure}
    assert got_ids == expected_ids, "every procedure section must get a relationship back, none lost across batches"

    # usage must be summed across every batch call, not just the last one
    assert result.usage.input_tokens == 111 * len(calls)
    assert result.usage.output_tokens == 22 * len(calls)


def test_discover_references_raises_llm_error_on_bad_batch(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    client = LLMClient()

    def fake_post(url, json, timeout):  # noqa: A002
        return _FakeResponse({"error": {"message": "boom"}}, status_code=400)

    monkeypatch.setattr(client._session, "post", fake_post)

    with pytest.raises(llm_client.LLMError):
        client.discover_references("Policy", [_section(1, 300)], "Procedure", [_section(2, 300)])
