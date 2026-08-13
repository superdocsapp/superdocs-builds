"""LLMClient: real tests, no live key required -- uses a fake Anthropic SDK
client instead of the network, matching the same pattern as
test_superdocs_client.py. Covers error classification, retry behavior, and
idempotency. Does NOT (cannot honestly) verify that a real model resists an
embedded instruction -- see test_prompt_injection.py for that, which requires
a real key at least once.
"""

from __future__ import annotations

from typing import Any, cast

import anthropic
import httpx
import pytest

from core.idempotency import IdempotencyStore
from core.llm import LLMClient, LLMPermanentError

_FAKE_RESULT: dict[str, Any] = {
    "doc_type": "contract",
    "confidence": 0.95,
    "reasoning": "has parties and terms",
    "contains_embedded_instruction": False,
}


class _FakeToolUseBlock:
    def __init__(self, name: str, input_: dict[str, Any]) -> None:
        self.type = "tool_use"
        self.name = name
        self.input = input_


class _FakeUsage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(
        self, content: list[_FakeToolUseBlock], usage: _FakeUsage | None = None
    ) -> None:
        self.content = content
        # usage deliberately omitted by default (not set to None as an
        # attribute): most existing tests' fakes have no .usage at all,
        # matching real production risk surface -- _record_usage's own
        # getattr(resp, "usage", None) is what has to handle that, not
        # this fake pretending every response carries one.
        if usage is not None:
            self.usage = usage


class _FakeMessages:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self._responses = responses
        self.calls = 0

    def create(self, **kwargs: Any) -> _FakeResponse:
        r = self._responses[self.calls]
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return r


class _FakeAnthropic:
    def __init__(self, responses: list[_FakeResponse | Exception]) -> None:
        self.messages = _FakeMessages(responses)


def _status_error(status: int) -> anthropic.APIStatusError:
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req, json={"error": "boom"})
    return anthropic.APIStatusError("boom", response=resp, body=None)


def _llm_client(fake: _FakeAnthropic, **kwargs: Any) -> LLMClient:
    """_FakeAnthropic duck-types core.llm's _AnthropicLike Protocol (a `.messages`
    with a `.create(...)`) but isn't nominally that Protocol -- mypy's structural
    check on **kwargs-returning methods is stricter than the runtime behavior
    actually requires. One documented cast here, rather than sprinkled at every
    call site, since this is a test-only concern."""
    return LLMClient(api_key="sk-ant-test", client=cast(Any, fake), **kwargs)


def test_happy_path() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("classify_document", _FAKE_RESULT)])])
    llm = _llm_client(fake)
    result = llm.classify_document("This is a services agreement between...")
    assert result == _FAKE_RESULT


def test_permanent_error_not_retried() -> None:
    fake = _FakeAnthropic([_status_error(422)])
    llm = _llm_client(fake)
    with pytest.raises(LLMPermanentError):
        llm.classify_document("some text")
    assert fake.messages.calls == 1


def test_transient_error_retried_until_success() -> None:
    fake = _FakeAnthropic(
        [
            _status_error(429),
            _status_error(429),
            _FakeResponse([_FakeToolUseBlock("classify_document", _FAKE_RESULT)]),
        ]
    )
    llm = _llm_client(fake)
    result = llm.classify_document("some text")
    assert result == _FAKE_RESULT
    assert fake.messages.calls == 3


def test_classify_document_is_idempotent(idempotency_store: IdempotencyStore) -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("classify_document", _FAKE_RESULT)])])
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    r1 = llm.classify_document("test: idempotency check unique text 12345")
    r2 = llm.classify_document("test: idempotency check unique text 12345")

    assert fake.messages.calls == 1, "a repeated classify_document call must not re-call the model"
    assert r1 == r2


def test_missing_tool_call_is_permanent_error() -> None:
    """If the model responds without the expected tool call at all (e.g. it
    just wrote text back), that's a permanent error, not something to retry
    into oblivion."""
    fake = _FakeAnthropic([_FakeResponse([])])
    llm = _llm_client(fake)
    with pytest.raises(LLMPermanentError):
        llm.classify_document("some text")
    assert fake.messages.calls == 1


_FAKE_FACTS_RESULT: dict[str, Any] = {
    "facts": [
        {
            "field": "monthly_fee",
            "value": "$18,500",
            "source_quote": "a monthly subscription fee of $18,500",
        }
    ]
}


def test_extract_facts_happy_path() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("extract_facts", _FAKE_FACTS_RESULT)])])
    llm = _llm_client(fake)
    result = llm.extract_facts("some contract text", "contract")
    assert result == _FAKE_FACTS_RESULT["facts"]


def test_extract_facts_is_idempotent(idempotency_store: IdempotencyStore) -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("extract_facts", _FAKE_FACTS_RESULT)])])
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    r1 = llm.extract_facts("test: extract idempotency unique text 67890", "contract")
    r2 = llm.extract_facts("test: extract idempotency unique text 67890", "contract")

    assert fake.messages.calls == 1, "a repeated extract_facts call must not re-call the model"
    assert r1 == r2


def test_extract_facts_missing_facts_key_returns_empty_list() -> None:
    """A defensive case: if the model's tool call somehow omits `facts`
    entirely, we return an empty list rather than raising -- an empty
    extraction is a valid (if unhelpful) result, not a crash."""
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("extract_facts", {})])])
    llm = _llm_client(fake)
    result = llm.extract_facts("some text", "invoice")
    assert result == []


def test_extract_facts_non_list_facts_value_returns_empty_list() -> None:
    """A real anomaly observed in production, not hypothesized: one live
    recording came back with the `facts` field itself serialized as a raw
    string (valid JSON text, but never re-parsed) instead of an actual
    list. Must be treated as empty and logged, not passed downstream where
    iterating over it would silently iterate character-by-character."""
    fake = _FakeAnthropic(
        [_FakeResponse([_FakeToolUseBlock("extract_facts", {"facts": '[{"field": "x"}]'})])]
    )
    llm = _llm_client(fake)
    result = llm.extract_facts("some text", "invoice")
    assert result == []


_FAKE_RECONCILE_RESULT: dict[str, Any] = {
    "findings": [
        {
            "subject": "monthly subscription fee",
            "fact_refs": [
                {"document_filename": "contract.txt", "field": "monthly_fee"},
                {"document_filename": "amendment.txt", "field": "new_fee"},
            ],
            "status": "superseded",
            "explanation": "amendment raises the fee",
            "resolved_value": "$21,000",
            "evidence_document_filename": "amendment.txt",
            "evidence_quote": "increase the monthly subscription fee to $21,000",
        }
    ]
}


def test_reconcile_facts_happy_path() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("reconcile_facts", _FAKE_RECONCILE_RESULT)])])
    llm = _llm_client(fake)
    result = llm.reconcile_facts("some facts context")
    assert result == _FAKE_RECONCILE_RESULT["findings"]


def test_reconcile_facts_is_idempotent(idempotency_store: IdempotencyStore) -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("reconcile_facts", _FAKE_RECONCILE_RESULT)])])
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    r1 = llm.reconcile_facts("test: reconcile idempotency unique text 13579")
    r2 = llm.reconcile_facts("test: reconcile idempotency unique text 13579")

    assert fake.messages.calls == 1, "a repeated reconcile_facts call must not re-call the model"
    assert r1 == r2


def test_reconcile_facts_missing_findings_key_returns_empty_list() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("reconcile_facts", {})])])
    llm = _llm_client(fake)
    result = llm.reconcile_facts("some facts context")
    assert result == []


_FAKE_COMPLIANCE_RESULT: dict[str, Any] = {
    "findings": [
        {
            "rule": "Payment terms must not exceed Net 45.",
            "status": "pass",
            "explanation": "contract specifies Net 30",
            "citation_document_filename": "contract.txt",
            "citation_quote": "Payment terms are Net 30.",
        }
    ]
}


def test_examine_compliance_happy_path() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("examine_compliance", _FAKE_COMPLIANCE_RESULT)])])
    llm = _llm_client(fake)
    result = llm.examine_compliance(["Payment terms must not exceed Net 45."], "some corpus text")
    assert result == _FAKE_COMPLIANCE_RESULT["findings"]


def test_examine_compliance_sends_checklist_and_corpus_in_the_message() -> None:
    """A real bug caught while building this: the checklist was hashed for
    idempotency but never actually included in the message sent to the
    model. Assert both the checklist and the corpus text genuinely reach
    the API call, not just the response-handling code."""
    captured: dict[str, Any] = {}

    class _CapturingMessages:
        def create(self, **kwargs: Any) -> _FakeResponse:
            captured.update(kwargs)
            return _FakeResponse([_FakeToolUseBlock("examine_compliance", _FAKE_COMPLIANCE_RESULT)])

    class _CapturingAnthropic:
        def __init__(self) -> None:
            self.messages = _CapturingMessages()

    llm = _llm_client(cast(_FakeAnthropic, _CapturingAnthropic()))
    llm.examine_compliance(["RULE_MARKER_ABC"], "CORPUS_MARKER_XYZ")

    sent_message = captured["messages"][0]["content"]
    assert "RULE_MARKER_ABC" in sent_message, "checklist never reached the model"
    assert "CORPUS_MARKER_XYZ" in sent_message, "corpus text never reached the model"


def test_examine_compliance_is_idempotent(idempotency_store: IdempotencyStore) -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("examine_compliance", _FAKE_COMPLIANCE_RESULT)])])
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    r1 = llm.examine_compliance(["test rule unique 24680"], "test corpus unique 24680")
    r2 = llm.examine_compliance(["test rule unique 24680"], "test corpus unique 24680")

    assert fake.messages.calls == 1, "a repeated examine_compliance call must not re-call the model"
    assert r1 == r2


def test_examine_compliance_missing_findings_key_returns_empty_list() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("examine_compliance", {})])])
    llm = _llm_client(fake)
    result = llm.examine_compliance(["some rule"], "some corpus")
    assert result == []


def test_usage_log_records_tokens_and_estimated_cost_from_a_real_shaped_response() -> None:
    fake = _FakeAnthropic(
        [
            _FakeResponse(
                [_FakeToolUseBlock("classify_document", _FAKE_RESULT)],
                usage=_FakeUsage(input_tokens=1000, output_tokens=200),
            )
        ]
    )
    llm = _llm_client(fake)
    llm.classify_document("some text")

    assert len(llm.usage_log) == 1
    record = llm.usage_log[0]
    assert record["tool_name"] == "classify_document"
    assert record["input_tokens"] == 1000
    assert record["output_tokens"] == 200
    # Cost pinned to the default model's published per-million-token
    # pricing in core/llm.py (3.0 input / 15.0 output USD per million):
    # (1000 * 3.0 + 200 * 15.0) / 1_000_000
    assert record["estimated_cost_usd"] == pytest.approx(0.006)


def test_usage_log_gracefully_zeroes_out_when_response_has_no_usage_attribute() -> None:
    """Most of this file's fakes (and every fake LLM client across the
    pipeline test suite) don't carry a .usage attribute at all -- this must
    never raise, just record zeroed usage. Real Anthropic SDK responses
    always have .usage; this is defense against a test double, not
    something production traffic should ever hit."""
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("classify_document", _FAKE_RESULT)])])
    llm = _llm_client(fake)
    llm.classify_document("some text")

    assert len(llm.usage_log) == 1
    assert llm.usage_log[0]["input_tokens"] == 0
    assert llm.usage_log[0]["output_tokens"] == 0
    assert llm.usage_log[0]["estimated_cost_usd"] == 0.0


def test_usage_log_not_appended_on_an_idempotent_cache_hit(
    idempotency_store: IdempotencyStore,
) -> None:
    """A cache hit makes zero real API calls -- it must not record usage as
    if a call happened. Recording a phantom charge on a cache hit would be
    exactly the kind of inflated-cost bluff Task 1's honesty standard
    exists to prevent, just applied to cost reporting instead of facts."""
    fake = _FakeAnthropic(
        [
            _FakeResponse(
                [_FakeToolUseBlock("classify_document", _FAKE_RESULT)],
                usage=_FakeUsage(input_tokens=500, output_tokens=100),
            )
        ]
    )
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    llm.classify_document("test: usage cache-hit check unique text 98765")
    llm.classify_document("test: usage cache-hit check unique text 98765")

    assert fake.messages.calls == 1
    assert len(llm.usage_log) == 1, "the cache hit must not append a second, phantom usage record"


_FAKE_REVREC_RESULT: dict[str, Any] = {
    "performance_obligations": [
        {
            "obligation_id": "software_license",
            "description": "Access to the SaaS platform",
            "source_quote": "Customer shall receive access to the Platform",
            "is_distinct": True,
            "is_judgement": False,
            "judgement_note": "",
        }
    ],
    "price_allocations": [
        {
            "obligation_id": "software_license",
            "allocated_amount": "$45,000",
            "allocation_basis": "stated explicitly in contract",
            "source_quote": "annual fee of $45,000",
            "is_judgement": False,
            "judgement_note": "",
        }
    ],
    "timing_conclusions": [
        {
            "obligation_id": "software_license",
            "recognition_pattern": "over_time",
            "timing_basis": "customer benefits from access throughout the term",
            "source_quote": "for a term of twelve (12) months",
            "is_judgement": False,
            "judgement_note": "",
        }
    ],
}


def test_analyze_revenue_recognition_happy_path() -> None:
    fake = _FakeAnthropic(
        [_FakeResponse([_FakeToolUseBlock("analyze_revenue_recognition", _FAKE_REVREC_RESULT)])]
    )
    llm = _llm_client(fake)
    result = llm.analyze_revenue_recognition("some contract text")
    assert result == _FAKE_REVREC_RESULT


def test_analyze_revenue_recognition_is_idempotent(idempotency_store: IdempotencyStore) -> None:
    fake = _FakeAnthropic(
        [_FakeResponse([_FakeToolUseBlock("analyze_revenue_recognition", _FAKE_REVREC_RESULT)])]
    )
    llm = _llm_client(fake, idempotency_store=idempotency_store)

    r1 = llm.analyze_revenue_recognition("test: revrec idempotency unique text 13579")
    r2 = llm.analyze_revenue_recognition("test: revrec idempotency unique text 13579")

    assert fake.messages.calls == 1, "a repeated call must not re-call the model"
    assert r1 == r2


def test_analyze_revenue_recognition_missing_fields_return_empty_lists() -> None:
    fake = _FakeAnthropic([_FakeResponse([_FakeToolUseBlock("analyze_revenue_recognition", {})])])
    llm = _llm_client(fake)
    result = llm.analyze_revenue_recognition("some text")
    assert result == {
        "performance_obligations": [],
        "price_allocations": [],
        "timing_conclusions": [],
    }


def test_analyze_revenue_recognition_non_list_field_returns_empty_list() -> None:
    """Same real anomaly class as extract_facts's non-list-facts test: a
    field mis-serialized as a raw string instead of a real array must not
    be passed downstream as if it were one."""
    fake = _FakeAnthropic(
        [
            _FakeResponse(
                [
                    _FakeToolUseBlock(
                        "analyze_revenue_recognition",
                        {
                            "performance_obligations": '[{"obligation_id": "x"}]',
                            "price_allocations": [],
                            "timing_conclusions": [],
                        },
                    )
                ]
            )
        ]
    )
    llm = _llm_client(fake)
    result = llm.analyze_revenue_recognition("some text")
    assert result["performance_obligations"] == []
