# Implementation Plan: Microfinance Ingestion Pipeline

## Overview

This plan implements the microfinance document classification and type-specific extraction pipeline. Work proceeds infrastructure-first (state extension, base classes, registry), then core logic (classifier node, extractors, source linker), then graph wiring, then test utilities (synthetic generator), and finally property-based and integration tests.

## Tasks

- [x] 1. Extend pipeline state and define extraction data models
  - [x] 1.1 Add classification fields to PipelineState
    - Add `classification_label: Optional[str]`, `classification_confidence: Optional[float]`, and `classification_scores: Optional[dict[str, float]]` to the `PipelineState` TypedDict in `src/pipeline/state.py`
    - Update `create_initial_state` to initialize these fields to `None`
    - _Requirements: 1.1, 1.2_

  - [x] 1.2 Create extractor base module with SourceSpan and ExtractedFact
    - Create `src/pipeline/extractors/__init__.py` and `src/pipeline/extractors/base.py`
    - Define `SourceSpan` dataclass (start_offset, end_offset, page_number, section_id)
    - Define `ExtractedFact` dataclass (field_name, value, confidence, source_span, fact_group_id)
    - Define `FactExtractor` Protocol with `async def extract(self, text: str, chunks: list[dict]) -> list[ExtractedFact]`
    - _Requirements: 2.1, 3.1, 4.1, 5.1_

  - [x] 1.3 Create extractor registry module
    - Create `src/pipeline/extractors/registry.py`
    - Define `EXTRACTOR_REGISTRY: dict[str, type[FactExtractor]]` mapping document type labels to extractor classes
    - Initially map to placeholder references (to be populated as extractors are built)
    - _Requirements: 2.1, 3.1, 4.1_

- [x] 2. Implement document classifier node
  - [x] 2.1 Create classify_document node
    - Create `src/pipeline/nodes/classify_document.py`
    - Define `DocumentType` literal type: `loan_agreement | modification_agreement | repayment_statement | unclassified`
    - Define `ClassificationResult` dataclass with label, confidence, and scores
    - Define `DocumentClassifierService` Protocol with `async def classify(self, text: str) -> ClassificationResult`
    - Implement `async def classify_document(state: PipelineState, *, classifier: Optional[DocumentClassifierService] = None) -> PipelineState`
    - On success: store classification_label, classification_confidence, classification_scores in state, set node_status="completed"
    - If all scores ≤ 0.6: set label to "unclassified" and escalate to route_to_queue
    - If classifier is None or raises transient error: return transient error state
    - _Requirements: 1.1, 1.2, 1.3, 1.6_

  - [x] 2.2 Add MIME type validation to classify_document
    - Before classification, check `state["mime_type"]` against supported set {application/pdf, application/vnd.openxmlformats-officedocument.wordprocessingml.document, text/plain}
    - If unsupported: return permanent error with code UNSUPPORTED_FORMAT
    - If extracted_text is None or empty: return permanent error with code PARSE_FAILURE
    - _Requirements: 1.4, 1.5_

  - [x]* 2.3 Write property test for classification output validity (Property 1)
    - **Property 1: Classification Output Validity**
    - Use Hypothesis to generate non-empty text strings; verify classifier always produces exactly one label from the valid set, confidence in [0.0, 1.0], and label is "unclassified" iff all scores ≤ 0.6
    - **Validates: Requirements 1.1, 1.2**

  - [x]* 2.4 Write property test for unsupported MIME rejection (Property 2)
    - **Property 2: Unsupported MIME Rejection**
    - Use Hypothesis to generate arbitrary MIME type strings not in the supported set; verify the node returns UNSUPPORTED_FORMAT error
    - **Validates: Requirements 1.4**

- [x] 3. Implement type-specific extractors
  - [x] 3.1 Implement LoanAgreementExtractor
    - Create `src/pipeline/extractors/loan_agreement.py`
    - Implement extraction of 9 required fields: borrower_name, lender_name, principal_amount, interest_rate, interest_type, tenure_months, repayment_frequency, processing_fee, penal_rate
    - Missing fields → value="not_found", confidence=0.0
    - Normalize monetary values to 2 decimal places
    - Normalize rates to annual percentage with 2 decimal places
    - Handle conflicting values: pick last-in-document, confidence ≤ 0.5
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

  - [x] 3.2 Implement ModificationExtractor
    - Create `src/pipeline/extractors/modification.py`
    - Extract per-term-change records: original_loan_reference, modified_field_name, original_value, new_value, effective_date
    - Only support: interest_rate, tenure_months, emi_amount, moratorium_period_months — skip unsupported fields
    - Group related fields by fact_group_id
    - Missing fields → value="not_found", confidence=0.0
    - Normalize rates, tenures, and monetary values appropriately
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 3.3 Implement RepaymentExtractor
    - Create `src/pipeline/extractors/repayment.py`
    - Extract per-row records: payment_date, amount_paid, late_fee_charged, outstanding_balance, row_index (1-based)
    - Normalize dates to ISO 8601 (YYYY-MM-DD)
    - Normalize monetary fields to 2 decimal places
    - Unparseable dates → value="unparseable", confidence=0.0
    - Blank/non-numeric monetary fields → value="not_found", confidence=0.0
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 3.4 Register all extractors in the registry
    - Update `src/pipeline/extractors/registry.py` to import and register LoanAgreementExtractor, ModificationExtractor, RepaymentExtractor
    - Update `src/pipeline/extractors/__init__.py` with public exports
    - _Requirements: 2.1, 3.1, 4.1_

  - [x]* 3.5 Write property test for extraction schema completeness (Property 3)
    - **Property 3: Extraction Schema Completeness**
    - For each document type, verify extraction always produces exactly the required field names
    - **Validates: Requirements 2.1, 3.1, 4.1**

  - [x]* 3.6 Write property test for missing field handling (Property 4)
    - **Property 4: Missing Field Handling**
    - Generate documents with deliberately missing fields; verify value="not_found" or "unparseable" with confidence=0.0
    - **Validates: Requirements 2.2, 2.4, 3.5, 4.5, 4.6**

  - [x]* 3.7 Write property test for monetary normalization (Property 5)
    - **Property 5: Monetary Normalization**
    - Generate monetary strings with various formats; verify output has exactly 2 decimal places
    - **Validates: Requirements 2.3, 4.3**

  - [x]* 3.8 Write property test for rate normalization (Property 6)
    - **Property 6: Rate Normalization**
    - Generate rate values; verify output is annual percentage with exactly 2 decimal places
    - **Validates: Requirements 2.5, 3.6**

  - [x]* 3.9 Write property test for confidence score bounds (Property 7)
    - **Property 7: Confidence Score Bounds**
    - For any extracted fact, verify confidence is in [0.0, 1.0] with ≤ 3 decimal places
    - **Validates: Requirements 2.6, 4.7**

  - [x]* 3.10 Write property test for conflict resolution (Property 8)
    - **Property 8: Conflict Resolution Picks Last Value**
    - Generate documents with multiple conflicting values; verify last-in-document is picked with confidence ≤ 0.5
    - **Validates: Requirements 2.7**

  - [x]* 3.11 Write property test for modification field filtering (Property 9)
    - **Property 9: Modification Field Filtering**
    - Generate modification documents with unsupported fields; verify they are skipped
    - **Validates: Requirements 3.2**

  - [x]* 3.12 Write property test for multi-change cardinality (Property 10)
    - **Property 10: Multi-Change Cardinality**
    - Generate modification docs with N term changes; verify exactly N fact groups produced
    - **Validates: Requirements 3.4**

  - [x]* 3.13 Write property test for date normalization (Property 11)
    - **Property 11: Date Normalization to ISO 8601**
    - Generate date strings in various formats; verify output matches YYYY-MM-DD
    - **Validates: Requirements 4.2**

  - [x]* 3.14 Write property test for sequential row indexing (Property 12)
    - **Property 12: Sequential Row Indexing**
    - Generate repayment statements with N rows; verify row_index values are 1..N with no gaps/duplicates
    - **Validates: Requirements 4.4**

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement source linker
  - [x] 5.1 Create SourceLinker class
    - Create `src/pipeline/source_linker.py`
    - Define `SourceResolutionError` exception with claim_id, source_location_id, and reason
    - Implement `attach(fact: ExtractedFact, document_version_id: str) -> SourceLocation` — validates start_offset < end_offset, creates SourceLocation model instance
    - Implement `resolve(source_location: SourceLocation, stored_text: str) -> str` — returns `text[start_offset:end_offset]`, raises SourceResolutionError for out-of-bounds or missing document_version_id
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

  - [x] 5.2 Create persist_fact utility function
    - Add `persist_fact(fact, document_version_id, run_id, document_type, session)` function to `src/pipeline/source_linker.py`
    - Maps ExtractedFact → Claim record (using compound claim_type format `{document_type}.{field_name}`)
    - Maps SourceSpan → SourceLocation record with FK to claim
    - Handles repayment row indexing in claim_type: `repayment_statement.row_{N}.{field_name}`
    - _Requirements: 5.1, 5.4_

  - [x]* 5.3 Write property test for source pointer structural validity (Property 13)
    - **Property 13: Source Pointer Structural Validity**
    - Generate ExtractedFacts; verify attached source pointers always have start_offset < end_offset and valid references
    - **Validates: Requirements 5.1, 5.2**

  - [x]* 5.4 Write property test for source pointer resolution correctness (Property 14)
    - **Property 14: Source Pointer Resolution Correctness**
    - Generate valid source pointers and text; verify resolve returns exactly `text[start_offset:end_offset]`
    - **Validates: Requirements 5.3**

  - [x]* 5.5 Write property test for extraction round-trip (Property 15)
    - **Property 15: Extraction Round-Trip**
    - Verify that resolving a pointer and re-parsing yields the same value as original extraction
    - **Validates: Requirements 5.5**

  - [x]* 5.6 Write property test for source resolution error reporting (Property 16)
    - **Property 16: Source Resolution Error Reporting**
    - Generate out-of-bounds offsets or invalid document_version_ids; verify SourceResolutionError raised with correct fields
    - **Validates: Requirements 5.6**

- [x] 6. Wire classify_document into the pipeline graph
  - [x] 6.1 Update pipeline graph and routing
    - Import `classify_document` in `src/pipeline/graph.py`
    - Add `"classify_document": classify_document` to `NODES` dict
    - Update `PATH_MAPS["extract_text"]` to route `"next"` → `"classify_document"` instead of `"chunk"`
    - Add `PATH_MAPS["classify_document"] = {"next": "chunk", "escalate": "route_to_queue", "retry": "classify_document"}`
    - Ensure routing.py generates correct routing function for the new node
    - _Requirements: 1.1, 1.2_

  - [x] 6.2 Extend extract_claims to dispatch by document type
    - Modify `src/pipeline/nodes/extract_claims.py` to check `state["classification_label"]`
    - If label is in EXTRACTOR_REGISTRY: dispatch to type-specific extractor, then run SourceLinker.attach on each fact
    - If label is "unclassified" or not in registry: fall back to existing generic extraction logic
    - Convert ExtractedFacts to ExtractionResult entries for downstream compatibility
    - _Requirements: 2.1, 3.1, 4.1, 5.1_

- [x] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. Implement synthetic document generator
  - [x] 8.1 Create synthetic generator module
    - Create `tests/synthetic/__init__.py` and `tests/synthetic/generator.py`
    - Define `GroundTruthFact`, `SyntheticDocument`, `ConflictEntry`, `ConflictManifest`, `SyntheticPile` dataclasses
    - Implement `SyntheticDocumentGenerator.__init__(seed: Optional[int])` with deterministic RNG
    - Implement `generate() -> SyntheticPile` producing exactly 5 documents (≥1 loan, ≥1 modification, ≥1 repayment), 2 factual conflicts, ≥2 formats, chronological coherence, shared loan reference
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [x]* 8.2 Write property test for generator output structure (Property 17)
    - **Property 17: Generator Output Structure**
    - For any integer seed, verify exactly 5 docs, ≥1 of each type, exactly 2 conflicts, ≥2 formats
    - **Validates: Requirements 6.1, 6.2, 6.4**

  - [x]* 8.3 Write property test for conflict manifest validity (Property 18)
    - **Property 18: Conflict Manifest Validity**
    - Verify each conflict entry references one modification and one repayment filename, with non-empty field_name, expected_value, contradicting_value
    - **Validates: Requirements 6.3, 6.6**

  - [x]* 8.4 Write property test for chronological coherence (Property 19)
    - **Property 19: Chronological Coherence**
    - Verify loan date < modification dates < repayment dates, and shared loan reference
    - **Validates: Requirements 6.7**

  - [x]* 8.5 Write property test for generator determinism (Property 20)
    - **Property 20: Generator Determinism**
    - For any seed, verify two invocations produce byte-identical output
    - **Validates: Requirements 6.8**

- [x] 9. Write test infrastructure and end-to-end provenance test
  - [x] 9.1 Create test conftest with Hypothesis strategies
    - Create `tests/microfinance/__init__.py` and `tests/microfinance/conftest.py`
    - Implement custom Hypothesis strategies: `loan_agreement_text`, `modification_text`, `repayment_text`, `monetary_string`, `date_string`, `source_pointer_and_text`
    - Add shared fixtures for classifier mock, extractor instances, and source linker
    - _Requirements: 2.1, 3.1, 4.1, 5.1_

  - [x] 9.2 Organize property test files
    - Create `tests/microfinance/test_properties_classifier.py` (Properties 1, 2)
    - Create `tests/microfinance/test_properties_extraction.py` (Properties 3–12)
    - Create `tests/microfinance/test_properties_source_linker.py` (Properties 13–16)
    - Create `tests/microfinance/test_properties_generator.py` (Properties 17–20)
    - Wire all property tests to use strategies from conftest
    - _Requirements: 1.1–6.8_

  - [x] 9.3 Implement end-to-end provenance test
    - Create `tests/microfinance/test_provenance_e2e.py`
    - Ingest all 5 synthetic documents through the pipeline
    - Assert: all 5 documents produce ≥1 fact, every fact has exactly 1 source_location, start_offset < end_offset, resolved substring is non-empty, round-trip re-parse yields same value, no SourceResolutionError raised
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

- [x] 10. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python throughout — all implementation uses Python with async/await and Hypothesis for PBT
- The existing `extract_claims` node is extended (not replaced) to support type-specific dispatch while preserving backward compatibility for non-microfinance documents

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["2.3", "2.4", "3.4", "5.1"] },
    { "id": 4, "tasks": ["3.5", "3.6", "3.7", "3.8", "3.9", "5.2"] },
    { "id": 5, "tasks": ["3.10", "3.11", "3.12", "3.13", "3.14", "5.3", "5.4"] },
    { "id": 6, "tasks": ["5.5", "5.6", "6.1"] },
    { "id": 7, "tasks": ["6.2"] },
    { "id": 8, "tasks": ["8.1", "9.1"] },
    { "id": 9, "tasks": ["8.2", "8.3", "8.4", "8.5", "9.2"] },
    { "id": 10, "tasks": ["9.3"] }
  ]
}
```
