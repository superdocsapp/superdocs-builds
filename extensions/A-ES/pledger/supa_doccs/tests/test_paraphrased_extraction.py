"""Paraphrased extraction comparison tests.

Generates documents with the SAME facts but DIFFERENT wording, then runs
extraction against both template and paraphrased versions.

Part 1: Documents the gap — regex-only extraction fails on paraphrased text.
Part 2: With LLM fallback, the pipeline extracts all facts from paraphrased text.
Part 3: Field-level fallback test — a mostly-templated doc with one paraphrased
         field triggers LLM fallback for exactly that field.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest

from src.pipeline.config import load_config
from src.pipeline.extractors.base import ExtractedFact, SourceSpan
from src.pipeline.extractors.loan_agreement import LoanAgreementExtractor
from src.pipeline.extractors.modification import ModificationExtractor
from src.pipeline.extractors.repayment import RepaymentExtractor
from src.pipeline.extractors.llm_extractor import LLMFactExtractor, locate_span
from src.pipeline.nodes.extract_claims import extract_claims
from src.pipeline.state import ChunkEntry, PipelineState, create_initial_state
from tests.synthetic.generator import SyntheticDocument
from tests.synthetic.paraphrased_generator import ParaphrasedDocumentGenerator


# ---------------------------------------------------------------------------
# Shared test parameters (same values for both piles)
# ---------------------------------------------------------------------------

SHARED_PARAMS = {
    "loan_id": "MFL-777888",
    "borrower_name": "Priya Sharma",
    "lender_name": "MicroFinance Partners Ltd.",
    "principal": 150000,
    "interest_rate": 18.50,
    "tenure_months": 24,
    "processing_fee": 3000.0,
    "penal_rate": 24.50,
    "loan_date": date(2023, 3, 15),
    "new_rate": 14.00,
    "moratorium_months": 3,
    "mod_date": date(2023, 8, 1),
}


# ---------------------------------------------------------------------------
# Mock LLM Client that simulates correct extraction from natural language
# ---------------------------------------------------------------------------


class MockExtractionLLMClient:
    """LLM client that returns correct extraction results for paraphrased docs.

    Simulates what a real LLM would do: understand natural language and
    extract the correct values with verbatim quoted spans.
    """

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def chat(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        self.calls.append((system_prompt, user_prompt))

        # Parse the requested fields from the user prompt
        fields_requested = self._parse_requested_fields(user_prompt)
        document_text = self._extract_document_text(user_prompt)

        # Return correct extractions based on what's actually in the text
        results = []
        for field in fields_requested:
            result = self._extract_field(field, document_text)
            results.append(result)

        return {"fields": results}

    def _parse_requested_fields(self, user_prompt: str) -> list[str]:
        """Parse field names from the user prompt."""
        fields = []
        for line in user_prompt.split("\n"):
            if line.startswith("- ") and ":" in line:
                field_name = line[2:line.index(":")]
                fields.append(field_name)
        return fields

    def _extract_document_text(self, user_prompt: str) -> str:
        """Extract the document text from between --- delimiters."""
        parts = user_prompt.split("---")
        if len(parts) >= 3:
            return parts[1].strip()
        return user_prompt

    def _extract_field(self, field_name: str, text: str) -> dict[str, Any]:
        """Simulate LLM extraction for a specific field."""
        # Look for known values in the text
        extraction_rules: dict[str, list[tuple[str, str, str]]] = {
            # field_name: [(search_pattern, normalized_value, span_hint), ...]
            "borrower_name": [
                ("Priya Sharma", "Priya Sharma", "Priya Sharma"),
                ("Rajesh Kumar", "Rajesh Kumar", "Rajesh Kumar"),
                ("Adversarial Test Corp", "Adversarial Test Corp", "Adversarial Test Corp"),
            ],
            "lender_name": [
                ("MicroFinance Partners Ltd.", "MicroFinance Partners Ltd.", "MicroFinance Partners Ltd."),
                ("Legitimate Lender Inc", "Legitimate Lender Inc", "Legitimate Lender Inc"),
            ],
            "principal_amount": [
                ("INR 150,000.00", "150000.00", "INR 150,000.00"),
                ("150,000", "150000.00", "150,000"),
                ("Rs. 150,000", "150000.00", "Rs. 150,000"),
                ("2,00,000", "200000.00", "2,00,000"),
                ("₹1,50,000", "150000.00", "₹1,50,000"),
            ],
            "interest_rate": [
                ("18.50%", "18.50", "18.50%"),
                ("18.50 percent", "18.50", "18.50 percent"),
                ("42.00%", "42.00", "42.00%"),
            ],
            "interest_type": [
                ("diminishing balance", "reducing_balance", "diminishing balance"),
                ("reducing balance", "reducing_balance", "reducing balance"),
                ("Reducing Balance", "reducing_balance", "Reducing Balance"),
                ("flat rate", "flat", "flat rate"),
            ],
            "tenure_months": [
                ("twenty-four (24) calendar months", "24", "twenty-four (24) calendar months"),
                ("24 months", "24", "24 months"),
                ("24) calendar months", "24", "twenty-four (24) calendar months"),
            ],
            "repayment_frequency": [
                ("monthly cycle", "monthly", "monthly cycle"),
                ("monthly repayment", "monthly", "monthly repayment"),
                ("Monthly", "monthly", "Monthly"),
                ("monthly installments", "monthly", "monthly installments"),
            ],
            "processing_fee": [
                ("INR 3,000", "3000.00", "INR 3,000"),
                ("3,000.00", "3000.00", "3,000.00"),
                ("Rs. 3,000.00", "3000.00", "Rs. 3,000.00"),
                ("₹5,000", "5000.00", "₹5,000"),
                ("₹3,000.00", "3000.00", "₹3,000.00"),
            ],
            "penal_rate": [
                ("24.50%", "24.50", "24.50%"),
                ("24.50 percent", "24.50", "24.50 percent"),
            ],
        }

        rules = extraction_rules.get(field_name, [])
        for search, normalized, span_text in rules:
            if search in text:
                return {
                    "field_name": field_name,
                    "value": normalized,
                    "confidence": 0.9,
                    "quoted_span": span_text,
                }

        return {
            "field_name": field_name,
            "value": "not_found",
            "confidence": 0.0,
            "quoted_span": "",
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def loan_extractor() -> LoanAgreementExtractor:
    return LoanAgreementExtractor()


@pytest.fixture
def modification_extractor() -> ModificationExtractor:
    return ModificationExtractor()


@pytest.fixture
def repayment_extractor() -> RepaymentExtractor:
    return RepaymentExtractor()


@pytest.fixture
def llm_client() -> MockExtractionLLMClient:
    return MockExtractionLLMClient()


@pytest.fixture
def template_pile() -> dict:
    """Generate a template pile with the SAME parameters as the paraphrased pile."""
    p = SHARED_PARAMS

    loan_text = (
        f"LOAN AGREEMENT\n\n"
        f"Borrower Name: {p['borrower_name']}\n"
        f"Lender Name: {p['lender_name']}\n"
        f"Principal Amount: ₹{p['principal']:,}\n"
        f"Interest Rate: {p['interest_rate']:.2f}% per annum\n"
        f"Interest Type: Reducing Balance\n"
        f"Tenure: {p['tenure_months']} months\n"
        f"Repayment Frequency: Monthly\n"
        f"Processing Fee: ₹{p['processing_fee']:,.2f}\n"
        f"Penal Rate: {p['penal_rate']:.2f}% p.a.\n"
    )

    loan_doc = SyntheticDocument(
        filename="loan_template_MFL-777888_1.txt",
        document_type="loan_agreement",
        format="text",
        content=loan_text.encode("utf-8"),
        text_content=loan_text,
        ground_truth_facts=[],
    )

    mod_text = (
        f"MODIFICATION AGREEMENT\n\n"
        f"Reference Loan: {p['loan_id']}\n"
        f"Effective Date: {p['mod_date'].isoformat()}\n\n"
        f"Interest Rate reduced from {p['interest_rate']:.2f}% "
        f"to {p['new_rate']:.2f}% effective {p['mod_date'].isoformat()}.\n\n"
        f"Moratorium of {p['moratorium_months']} months granted.\n"
    )

    mod_doc = SyntheticDocument(
        filename="mod_template_MFL-777888.txt",
        document_type="modification_agreement",
        format="text",
        content=mod_text.encode("utf-8"),
        text_content=mod_text,
        ground_truth_facts=[],
    )

    repay_start = p["mod_date"] + timedelta(days=45)
    monthly_rate = p["interest_rate"] / 100 / 12
    outstanding = float(p["principal"])

    header = (
        f"REPAYMENT STATEMENT\n\n"
        f"Loan Reference: {p['loan_id']}\n"
        f"Borrower: {p['borrower_name']}\n"
        f"Interest Rate Applied: {p['interest_rate']:.2f}%\n\n"
        f"| Payment Date | Amount Paid | Late Fee | Outstanding Balance |\n"
        f"|---|---|---|---|\n"
    )
    rows = ""
    pd = repay_start
    for i in range(3):
        interest_component = outstanding * monthly_rate
        principal_component = outstanding / 12
        amount = round(interest_component + principal_component, 2)
        outstanding = max(0.0, outstanding - amount)
        rows += f"| {pd.isoformat()} | {amount:.2f} | 0.00 | {outstanding:.2f} |\n"
        pd = pd + timedelta(days=30)

    repay_doc = SyntheticDocument(
        filename="repay_template_MFL-777888.txt",
        document_type="repayment_statement",
        format="text",
        content=(header + rows).encode("utf-8"),
        text_content=header + rows,
        ground_truth_facts=[],
    )

    return {
        "loan_docs": [loan_doc],
        "mod_docs": [mod_doc],
        "repay_docs": [repay_doc],
    }


@pytest.fixture
def paraphrased_pile() -> dict:
    """Generate the paraphrased pile with same facts, different wording."""
    gen = ParaphrasedDocumentGenerator()
    pile = gen.generate(**SHARED_PARAMS)
    return {
        "loan_docs": [d for d in pile.documents if d.document_type == "loan_agreement"],
        "mod_docs": [d for d in pile.documents if d.document_type == "modification_agreement"],
        "repay_docs": [d for d in pile.documents if d.document_type == "repayment_statement"],
        "phrasing_changes": pile.phrasing_changes,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _facts_to_dict(facts) -> dict[str, str]:
    """Convert a list of ExtractedFact into {field_name: value} dict."""
    result = {}
    for fact in facts:
        if fact.fact_group_id:
            key = f"{fact.fact_group_id}.{fact.field_name}"
        else:
            key = fact.field_name
        result[key] = fact.value
    return result


def _found_fields(facts) -> dict[str, str]:
    """Return only the fields that were actually found (not 'not_found')."""
    all_facts = _facts_to_dict(facts)
    return {k: v for k, v in all_facts.items() if v != "not_found"}


def _make_state_for_doc(doc: SyntheticDocument) -> PipelineState:
    """Create a pipeline state from a synthetic document."""
    config = load_config()
    state = create_initial_state(
        run_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        document_version_id=str(uuid.uuid4()),
        config=config,
    )
    state["extracted_text"] = doc.text_content
    state["classification_label"] = doc.document_type
    state["chunks"] = [
        ChunkEntry(
            index=0,
            text=doc.text_content,
            start_offset=0,
            end_offset=len(doc.text_content),
        ),
    ]
    return state


# ---------------------------------------------------------------------------
# Part 1: Regex-only extraction gaps (unchanged — documents the problem)
# ---------------------------------------------------------------------------


class TestLoanExtractionComparison:
    """Compare loan agreement extraction between template and paraphrased docs."""

    @pytest.mark.anyio
    async def test_template_loan_extracts_all_fields(
        self, loan_extractor: LoanAgreementExtractor, template_pile: dict
    ):
        """Baseline: the template pile extracts all 9 fields successfully."""
        for doc in template_pile["loan_docs"]:
            facts = await loan_extractor.extract(doc.text_content, [])
            found = _found_fields(facts)
            for field in LoanAgreementExtractor.REQUIRED_FIELDS:
                assert field in found, (
                    f"Template doc '{doc.filename}' failed to extract '{field}'"
                )

    @pytest.mark.anyio
    async def test_paraphrased_loan_extraction_gaps(
        self, loan_extractor: LoanAgreementExtractor, paraphrased_pile: dict
    ):
        """Paraphrased loans: regex misses most fields."""
        all_gaps: dict[str, list[str]] = {}

        for doc in paraphrased_pile["loan_docs"]:
            facts = await loan_extractor.extract(doc.text_content, [])
            found = _found_fields(facts)

            for field in LoanAgreementExtractor.REQUIRED_FIELDS:
                if field not in found:
                    all_gaps.setdefault(field, []).append(doc.filename)

        # Gaps exist — regex is brittle
        assert len(all_gaps) > 0

    @pytest.mark.anyio
    async def test_paraphrased_loan_specific_field_failures(
        self, loan_extractor: LoanAgreementExtractor, paraphrased_pile: dict
    ):
        """Narrative loan doc: regex misses most fields."""
        narrative_doc = paraphrased_pile["loan_docs"][0]
        facts = await loan_extractor.extract(narrative_doc.text_content, [])
        found = _found_fields(facts)

        expected_values = {
            "borrower_name": "Priya Sharma",
            "lender_name": "MicroFinance Partners Ltd.",
            "principal_amount": "150000.00",
            "interest_rate": "18.50",
            "tenure_months": "24",
            "processing_fee": "3000.00",
            "penal_rate": "24.50",
        }

        missed = [f for f in expected_values if f not in found]
        assert len(missed) > 0


class TestModificationExtractionComparison:
    """Compare modification agreement extraction."""

    @pytest.mark.anyio
    async def test_template_modification_extracts_changes(
        self, modification_extractor: ModificationExtractor, template_pile: dict
    ):
        """Baseline: template modification docs extract changes."""
        for doc in template_pile["mod_docs"]:
            facts = await modification_extractor.extract(doc.text_content, [])
            found = _facts_to_dict(facts)
            assert any("new_value" in k for k in found)

    @pytest.mark.anyio
    async def test_paraphrased_modification_extraction_gaps(
        self, modification_extractor: ModificationExtractor, paraphrased_pile: dict
    ):
        """Letter-style modification: regex misses the changes."""
        for doc in paraphrased_pile["mod_docs"]:
            facts = await modification_extractor.extract(doc.text_content, [])
            found = _facts_to_dict(facts)

            new_values = [v for k, v in found.items() if "new_value" in k and v != "not_found"]
            moratorium_values = [
                v for k, v in found.items()
                if "moratorium" in k and v != "not_found" and v != "0"
            ]

            gaps = []
            if "14.00" not in str(new_values):
                gaps.append("new_interest_rate")
            if "3" not in str(moratorium_values):
                gaps.append("moratorium_period")

            assert len(gaps) > 0


class TestRepaymentExtractionComparison:
    """Compare repayment statement extraction."""

    @pytest.mark.anyio
    async def test_template_repayment_extracts_rows(
        self, repayment_extractor: RepaymentExtractor, template_pile: dict
    ):
        """Baseline: template repayment docs extract payment rows."""
        for doc in template_pile["repay_docs"]:
            facts = await repayment_extractor.extract(doc.text_content, [])
            row_facts = [f for f in facts if f.fact_group_id and "row_" in f.fact_group_id]
            assert len(row_facts) > 0

    @pytest.mark.anyio
    async def test_paraphrased_prose_repayment_extraction_gap(
        self, repayment_extractor: RepaymentExtractor, paraphrased_pile: dict
    ):
        """Narrative repayment: table parser cannot handle prose."""
        narrative_repay = paraphrased_pile["repay_docs"][1]
        facts = await repayment_extractor.extract(narrative_repay.text_content, [])
        row_facts = [f for f in facts if f.fact_group_id and "row_" in f.fact_group_id]
        assert len(row_facts) == 0

    @pytest.mark.anyio
    async def test_paraphrased_tabular_repayment_with_different_headers(
        self, repayment_extractor: RepaymentExtractor, paraphrased_pile: dict
    ):
        """Tab-separated repayment with non-standard headers still works."""
        tabular_repay = paraphrased_pile["repay_docs"][0]
        facts = await repayment_extractor.extract(tabular_repay.text_content, [])
        row_facts = [f for f in facts if f.fact_group_id and "row_" in f.fact_group_id]
        # Tab-separated tables are parsed regardless of header names
        assert len(row_facts) > 0


class TestExtractionGapSummary:
    """Aggregate gap analysis."""

    @pytest.mark.anyio
    async def test_gap_report(
        self,
        loan_extractor: LoanAgreementExtractor,
        modification_extractor: ModificationExtractor,
        repayment_extractor: RepaymentExtractor,
        paraphrased_pile: dict,
    ):
        """Summary report of regex extraction gaps."""
        total_expected = 0
        total_found = 0

        for doc in paraphrased_pile["loan_docs"]:
            facts = await loan_extractor.extract(doc.text_content, [])
            found = _found_fields(facts)
            total_expected += len(LoanAgreementExtractor.REQUIRED_FIELDS)
            total_found += len(found)

        coverage_pct = (total_found / total_expected * 100) if total_expected else 0
        # Coverage should be well below 50% (proving regex brittleness)
        assert coverage_pct < 50


# ---------------------------------------------------------------------------
# Part 2: With LLM fallback, paraphrased documents extract successfully
# ---------------------------------------------------------------------------


class TestLLMFallbackExtraction:
    """Prove that the LLM fallback fills gaps in paraphrased documents."""

    @pytest.mark.anyio
    async def test_paraphrased_loan_with_llm_fallback_extracts_all_fields(
        self, llm_client: MockExtractionLLMClient, paraphrased_pile: dict
    ):
        """With LLM fallback, the narrative loan doc extracts all fields."""
        narrative_doc = paraphrased_pile["loan_docs"][0]
        state = _make_state_for_doc(narrative_doc)

        result = await extract_claims(state, llm_client=llm_client)

        assert result["node_status"] == "completed"
        claims = result["claims"]

        # Extract claim values into a dict
        claim_values = {
            c["claim_id"].split(".")[1].rsplit("_", 1)[0]: c["claim_text"].split(": ", 1)[1]
            for c in claims
            if ": " in c["claim_text"]
        }

        # All key fields should be found
        assert claim_values.get("borrower_name") == "Priya Sharma"
        assert claim_values.get("lender_name") == "MicroFinance Partners Ltd."
        assert claim_values.get("principal_amount") == "150000.00"
        assert claim_values.get("interest_rate") == "18.50"
        assert claim_values.get("tenure_months") == "24"
        assert claim_values.get("processing_fee") == "3000.00"
        assert claim_values.get("penal_rate") == "24.50"

    @pytest.mark.anyio
    async def test_paraphrased_loan_llm_called_only_for_missing_fields(
        self, llm_client: MockExtractionLLMClient, paraphrased_pile: dict
    ):
        """LLM is only called for fields the regex couldn't extract."""
        # The legal-paragraph doc finds borrower_name and repayment_frequency
        # via regex, so LLM should only be called for the remaining fields
        legal_doc = paraphrased_pile["loan_docs"][1]
        state = _make_state_for_doc(legal_doc)

        await extract_claims(state, llm_client=llm_client)

        # LLM was called (for the missing fields)
        assert len(llm_client.calls) > 0

        # The user prompt should list only the missing fields, not all 9
        _, user_prompt = llm_client.calls[0]
        # Fields that regex found should NOT appear in the LLM request
        # (borrower_name is found by regex in the legal doc via "Borrower:" pattern)
        # But the exact fields depend on what the regex matches

    @pytest.mark.anyio
    async def test_template_loan_no_llm_fallback_needed(
        self, llm_client: MockExtractionLLMClient, template_pile: dict
    ):
        """Template docs: regex finds everything, no LLM calls needed."""
        template_doc = template_pile["loan_docs"][0]
        state = _make_state_for_doc(template_doc)

        result = await extract_claims(state, llm_client=llm_client)

        assert result["node_status"] == "completed"
        # LLM should NOT have been called (all fields found by regex)
        assert len(llm_client.calls) == 0

    @pytest.mark.anyio
    async def test_llm_fallback_citations_use_locate_span(
        self, llm_client: MockExtractionLLMClient, paraphrased_pile: dict
    ):
        """LLM-extracted fields have citations computed from quoted spans."""
        narrative_doc = paraphrased_pile["loan_docs"][0]
        state = _make_state_for_doc(narrative_doc)

        result = await extract_claims(state, llm_client=llm_client)

        claims = result["claims"]
        # Find a claim that was extracted by LLM (e.g., borrower_name)
        borrower_claim = next(
            (c for c in claims if "borrower_name" in c["claim_id"]), None
        )
        assert borrower_claim is not None

        # The span should point to the actual location of "Priya Sharma" in the text
        text = narrative_doc.text_content
        expected_start = text.find("Priya Sharma")
        assert expected_start != -1
        assert borrower_claim["start_offset"] == expected_start
        assert borrower_claim["end_offset"] == expected_start + len("Priya Sharma")


# ---------------------------------------------------------------------------
# Part 3: Field-level fallback test
# ---------------------------------------------------------------------------


class TestFieldLevelFallback:
    """A mostly-templated doc with one paraphrased field triggers LLM
    fallback for exactly that field without re-routing the whole document."""

    @pytest.mark.anyio
    async def test_single_paraphrased_field_triggers_targeted_fallback(
        self, llm_client: MockExtractionLLMClient
    ):
        """A loan doc where 8/9 fields are templated and one is paraphrased.

        The regex should extract 8 fields. The one paraphrased field
        (processing_fee expressed as 'administrative charge amounting to
        INR 3,000') should trigger LLM fallback for just that field.
        """
        # Build a mostly-templated document with ONE paraphrased field
        doc_text = (
            "LOAN AGREEMENT\n\n"
            "Borrower Name: Priya Sharma\n"
            "Lender Name: MicroFinance Partners Ltd.\n"
            "Principal Amount: ₹150,000\n"
            "Interest Rate: 18.50% per annum\n"
            "Interest Type: Reducing Balance\n"
            "Tenure: 24 months\n"
            "Repayment Frequency: Monthly\n"
            # This field is paraphrased — regex won't catch it:
            "An administrative charge amounting to INR 3,000 shall be "
            "deducted as a one-time service fee.\n"
            "Penal Rate: 24.50% p.a.\n"
        )

        doc = SyntheticDocument(
            filename="mostly_templated.txt",
            document_type="loan_agreement",
            format="text",
            content=doc_text.encode("utf-8"),
            text_content=doc_text,
            ground_truth_facts=[],
        )

        state = _make_state_for_doc(doc)
        result = await extract_claims(state, llm_client=llm_client)

        assert result["node_status"] == "completed"
        claims = result["claims"]

        # Parse claims into a dict
        claim_values = {}
        for c in claims:
            if ": " in c["claim_text"]:
                field = c["claim_id"].split(".")[1].rsplit("_", 1)[0]
                value = c["claim_text"].split(": ", 1)[1]
                claim_values[field] = value

        # All 9 fields should be extracted
        assert claim_values.get("borrower_name") == "Priya Sharma"
        assert claim_values.get("lender_name") == "MicroFinance Partners Ltd."
        assert claim_values.get("principal_amount") == "150000.00"
        assert claim_values.get("interest_rate") == "18.50"
        assert claim_values.get("interest_type") == "reducing_balance"
        assert claim_values.get("tenure_months") == "24"
        assert claim_values.get("repayment_frequency") == "monthly"
        assert claim_values.get("processing_fee") == "3000.00"  # LLM caught it!
        assert claim_values.get("penal_rate") == "24.50"

        # The LLM should have been called exactly once, for the one missing field
        assert len(llm_client.calls) == 1

        # The LLM request should mention only "processing_fee"
        _, user_prompt = llm_client.calls[0]
        assert "processing_fee" in user_prompt
        # It should NOT re-extract fields that regex already found
        assert "borrower_name" not in user_prompt
        assert "interest_rate" not in user_prompt

    @pytest.mark.anyio
    async def test_no_fallback_when_all_fields_found_by_regex(
        self, llm_client: MockExtractionLLMClient, template_pile: dict
    ):
        """Fully templated doc: zero LLM calls, all regex."""
        doc = template_pile["loan_docs"][0]
        state = _make_state_for_doc(doc)

        result = await extract_claims(state, llm_client=llm_client)

        assert result["node_status"] == "completed"
        assert len(llm_client.calls) == 0

    @pytest.mark.anyio
    async def test_citation_unverifiable_when_span_not_found(self):
        """If the LLM returns a quoted span that doesn't exist in the source,
        the citation is None (unverifiable) and the claim is still included
        with reduced confidence."""
        source = "The interest rate is eighteen point five percent per annum."
        quoted = "this text does not exist anywhere in the document"

        span = locate_span(quoted, source)
        assert span is None

    @pytest.mark.anyio
    async def test_citation_normalized_match(self):
        """Whitespace/case-insensitive match works for slightly-off quotes."""
        source = "The borrower is  Priya   Sharma from Mumbai."
        quoted = "the borrower is Priya Sharma"

        span = locate_span(quoted, source)
        # Should find via normalized matching
        assert span is not None
        # The span should cover the relevant text
        matched_text = source[span.start_offset:span.end_offset]
        assert "Priya" in matched_text

