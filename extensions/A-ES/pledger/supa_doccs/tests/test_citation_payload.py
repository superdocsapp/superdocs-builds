"""Tests for the canonical approval-queue citation builder.

Guarantees every enqueued citation carries document identity, a resolved
readable snippet, and that corrupt/zero spans degrade to unverifiable
(the (0,0) sentinel from extract_claims can never pose as a location).

Also covers truthful evaluation_method resolution (Prompt 4.3): the
value must reflect the path that actually ran — structured/deterministic
vs LLM — never a constant stamped at enqueue time.
"""

import asyncio
import uuid

import pytest

from src.pipeline.citation_payload import (
    build_source_citation,
    resolve_evaluation_method,
)

SOURCE = "X" * 100 + "The annual interest rate on the principal is 12.5% per annum." + "Y" * 100


def _claim(**overrides):
    claim = {
        "claim_id": "loan_agreement.interest_1",
        "claim_text": "interest rate",
        "citation_status": "grounded",
        "start_offset": 100,
        "end_offset": 174,
    }
    claim.update(overrides)
    return claim


def test_grounded_claim_gets_document_identity_and_snippet():
    citation = build_source_citation(
        _claim(),
        document_id="doc-123",
        document_version_id="ver-456",
        extracted_text=SOURCE,
    )
    assert citation["document_id"] == "doc-123"
    assert citation["document_version_id"] == "ver-456"
    assert citation["citation_status"] == "grounded"
    assert citation["snippet"] == SOURCE[100:174]
    assert citation["source_location"]["start_offset"] == 100
    # context fields are populated
    assert len(citation["snippet_context_before"]) > 0


def test_unverifiable_sentinel_span_stays_unverifiable_with_null_location():
    """The extract_claims (0, 0) sentinel must never render as a real span."""
    citation = build_source_citation(
        _claim(start_offset=0, end_offset=0),
        document_id="doc-123",
        document_version_id="ver-456",
        extracted_text=SOURCE,
    )
    assert citation["citation_status"] == "unverifiable"
    assert citation["source_location"] is None
    assert citation["snippet"] is None
    # identity survives even without a usable span
    assert citation["document_id"] == "doc-123"


def test_out_of_range_span_degrades_to_unverifiable():
    citation = build_source_citation(
        _claim(end_offset=10_000),
        document_id="doc-123",
        document_version_id="ver-456",
        extracted_text=SOURCE,
    )
    assert citation["citation_status"] == "unverifiable"
    assert citation["source_location"] is None


def test_inverted_span_degrades_to_unverifiable():
    citation = build_source_citation(
        _claim(start_offset=50, end_offset=40),
        document_id="doc-123",
        document_version_id="ver-456",
        extracted_text=SOURCE,
    )
    assert citation["citation_status"] == "unverifiable"


def test_missing_document_identity_is_explicit_null_not_omitted():
    citation = build_source_citation(_claim(), document_id=None, document_version_id=None)
    assert "document_id" in citation
    assert citation["document_id"] is None
    assert citation["document_version_id"] is None


def test_optional_location_metadata_is_carried_through():
    citation = build_source_citation(
        _claim(),
        document_id="doc-123",
        document_version_id="ver-456",
        page_number=4,
        section_id="sec-3.1",
        clause_ref="§3.1.2",
    )
    loc = citation["source_location"]
    assert loc["page_number"] == 4
    assert loc["section_id"] == "sec-3.1"
    assert loc["clause_ref"] == "§3.1.2"


@pytest.mark.parametrize("text", [None, SOURCE])
def test_snippet_only_when_source_text_available(text):
    citation = build_source_citation(
        _claim(),
        document_id="doc-123",
        document_version_id="ver-456",
        extracted_text=text,
    )
    if text is None:
        assert citation["snippet"] is None
    else:
        assert citation["snippet"] == SOURCE[100:174]


# ---------------------------------------------------------------------------
# Prompt 4.3: evaluation_method reflects the path that actually ran
# ---------------------------------------------------------------------------


class TestResolveEvaluationMethod:
    def test_structured_extraction_yields_structured(self):
        claim = {"claim_id": "c1", "_extraction_method": "structured"}
        assert resolve_evaluation_method(claim) == "structured"

    def test_regex_fallback_is_deterministic_not_llm(self):
        claim = {"claim_id": "c1", "_extraction_method": "regex_fallback"}
        assert resolve_evaluation_method(claim) == "structured"

    def test_llm_fallback_is_llm(self):
        claim = {"claim_id": "c1", "_extraction_method": "llm_fallback"}
        assert resolve_evaluation_method(claim) == "llm"

    def test_claim_linked_rule_finding_wins_over_extraction(self):
        """A structured rule check on an LLM-extracted claim → structured."""
        claim = {"claim_id": "c1", "_extraction_method": "llm"}
        findings = [
            {
                "claim_id": "c1",
                "rule_id": "USURY-36.1",
                "evaluation_method": "structured",
            }
        ]
        assert resolve_evaluation_method(claim, findings) == "structured"

    def test_other_claims_findings_are_ignored(self):
        claim = {"claim_id": "c1", "_extraction_method": "llm"}
        findings = [
            {"claim_id": "c2", "evaluation_method": "structured"},
        ]
        assert resolve_evaluation_method(claim, findings) == "llm"

    def test_no_provenance_recorded_is_unknown_never_defaulted_to_llm(self):
        assert resolve_evaluation_method({"claim_id": "c1"}) == "unknown"


class TestEnqueueEndToEnd:
    """Through _node_human_review enqueue: the stored queue payload must
    carry the method of the path that actually ran — a structured rule
    check must surface as 'structured', never the old hardcoded 'llm'."""

    def _enqueue(self, claims, claim_findings=None):
        from src.pipeline.approval import (
            ApprovalService,
            InMemoryApprovalStore,
        )
        from src.pipeline.approval_api import set_approval_service
        from src.pipeline.config import load_config
        from src.pipeline.demo_executor import _node_human_review
        from src.pipeline.state import create_initial_state

        service = ApprovalService(InMemoryApprovalStore())
        set_approval_service(service)
        try:
            run_id = str(uuid.uuid4())
            state = create_initial_state(
                run_id=run_id,
                document_id=str(uuid.uuid4()),
                document_version_id=str(uuid.uuid4()),
                config=load_config(),
            )
            state["queue_buckets"] = {
                "auto_approve": [],
                "escalate": [c["claim_id"] for c in claims],
                "auto_reject": [],
            }
            state["claims"] = claims
            if claim_findings is not None:
                state["claim_findings"] = claim_findings

            asyncio.run(_node_human_review(state, {"run_id": run_id}))
            pending = service.get_pending(run_id)
            assert len(pending) == 1
            return pending[0]
        finally:
            set_approval_service(None)

    def test_structured_check_shows_structured_end_to_end(self):
        item = self._enqueue(
            claims=[
                {
                    "claim_id": "loan_agreement.apr_1",
                    "claim_text": "APR is 42%",
                    "confidence": 0.9,
                    "citation_status": "grounded",
                    "_extraction_method": "structured",
                }
            ],
            claim_findings=[
                {
                    "claim_id": "loan_agreement.apr_1",
                    "rule_id": "USURY-36.1",
                    "evaluation_method": "structured",
                }
            ],
        )
        # Through enqueue AND API serialization (payload passes through
        # QueueItemResponse verbatim), the UI reads this dict directly.
        assert (
            item.payload["details"]["evaluation_method"] == "structured"
        ), "a deterministic rule finding must not be labeled 'llm'"

    def test_regex_extracted_claim_is_structured_not_llm(self):
        item = self._enqueue(
            claims=[
                {
                    "claim_id": "loan_agreement.fee_1",
                    "claim_text": "Processing fee ₹5,000",
                    "confidence": 0.6,
                    "citation_status": "grounded",
                    "_extraction_method": "regex_fallback",
                }
            ],
        )
        assert item.payload["details"]["evaluation_method"] == "structured"

    def test_llm_path_still_reports_llm(self):
        item = self._enqueue(
            claims=[
                {
                    "claim_id": "loan_agreement.term_1",
                    "claim_text": "Tenure is 24 months",
                    "confidence": 0.8,
                    "citation_status": "grounded",
                    "_extraction_method": "llm",
                }
            ],
        )
        assert item.payload["details"]["evaluation_method"] == "llm"
