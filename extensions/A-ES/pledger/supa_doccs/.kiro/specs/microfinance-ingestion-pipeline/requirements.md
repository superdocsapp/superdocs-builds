# Requirements Document

## Introduction

This specification defines an ingestion pipeline for microfinance loan documents. The pipeline accepts loan agreements, modification/restructuring agreements, and repayment statements in PDF, DOCX, or plain-text format. It classifies each document by type, extracts domain-specific structured facts, and stores every extracted fact with a precise source pointer (document id, page/section, character span) that can be resolved back to the original text. The specification also covers synthetic test data generation with deliberate factual conflicts and an end-to-end provenance test.

## Glossary

- **Pipeline**: The ingestion system that receives raw documents and produces classified, extracted, source-linked facts
- **Document_Classifier**: The subsystem responsible for determining whether a document is a loan agreement, modification/restructuring agreement, or repayment statement
- **Fact_Extractor**: The subsystem responsible for pulling structured data fields from classified documents
- **Source_Linker**: The subsystem responsible for attaching a resolvable provenance pointer to each extracted fact
- **Loan_Agreement**: A document that establishes borrower/lender identity, principal, interest rate, tenure, repayment frequency, processing fee, and penal rate
- **Modification_Agreement**: A document that amends one or more terms of an existing loan (rate change, tenure extension, EMI restructuring, moratorium grant)
- **Repayment_Statement**: A document recording individual payments with date, amount, late fee, and running outstanding balance
- **Source_Pointer**: A composite reference comprising document_version_id, page_number (or section_id), start_offset, and end_offset that locates extracted text within the original document. Offsets are 0-based character positions relative to the beginning of the page or section text.
- **Synthetic_Generator**: The subsystem that produces realistic test documents with controlled factual conflicts
- **Factual_Conflict**: A situation where a fact in one document contradicts a logically dependent fact in another document within the same pile (e.g., a modification lowers the interest rate but a subsequent repayment statement still bills at the original rate)
- **Flat_Rate**: Interest calculated on the full original principal for the entire tenure
- **Reducing_Balance_Rate**: Interest calculated on the outstanding principal after each repayment

## Requirements

### Requirement 1: Document Classification

**User Story:** As a compliance analyst, I want each ingested document automatically classified by type, so that the correct extraction logic is applied without manual triage.

#### Acceptance Criteria

1. WHEN a document in PDF, DOCX, or plain-text format is submitted, THE Document_Classifier SHALL assign exactly one classification label from the set {loan_agreement, modification_agreement, repayment_statement}
2. IF the Document_Classifier assigns a confidence score at or below 0.6 to all candidate labels, THEN THE Document_Classifier SHALL label the document as "unclassified" and route it to the approval queue for human review within the same processing transaction
3. THE Document_Classifier SHALL produce a classification result within 10 seconds per document for documents up to 50 pages
4. IF the submitted document has an unsupported MIME type (not PDF, DOCX, or plain text), THEN THE Pipeline SHALL reject the document with error code UNSUPPORTED_FORMAT and a descriptive message
5. IF a submitted document is in a supported format but cannot be parsed (zero extractable text, corrupted content, or encoding errors), THEN THE Pipeline SHALL reject the document with error code PARSE_FAILURE and a message indicating the nature of the parsing failure
6. IF a submitted document exceeds 50 pages, THEN THE Document_Classifier SHALL still produce a classification result, with a maximum processing time of 30 seconds

### Requirement 2: Loan Agreement Fact Extraction

**User Story:** As a compliance analyst, I want all material terms extracted from loan agreements, so that I can audit loan portfolios without reading each agreement manually.

#### Acceptance Criteria

1. WHEN a document is classified as loan_agreement, THE Fact_Extractor SHALL extract the following fields: borrower_name, lender_name, principal_amount, interest_rate, interest_type (flat or reducing_balance), tenure_months, repayment_frequency (one of: monthly, quarterly, semi_annually, annually, bullet), processing_fee, penal_rate
2. WHEN a required field is not present or not legible in the source document, THE Fact_Extractor SHALL record that field as "not_found" with confidence 0.0
3. THE Fact_Extractor SHALL normalize principal_amount and processing_fee to numeric values with exactly 2 decimal places in the document's stated currency
4. IF the source document does not state a currency, THEN THE Fact_Extractor SHALL record principal_amount and processing_fee as "not_found" with confidence 0.0
5. THE Fact_Extractor SHALL normalize interest_rate and penal_rate to annual percentage values with exactly 2 decimal places
6. THE Fact_Extractor SHALL assign a confidence score between 0.0 and 1.0 (inclusive, 3 decimal places precision) to each extracted field
7. IF a source document contains multiple conflicting values for the same field, THEN THE Fact_Extractor SHALL extract the value from the latest-dated clause or the clause appearing last in document order, and assign a confidence score no higher than 0.5

### Requirement 3: Modification Agreement Fact Extraction

**User Story:** As a compliance analyst, I want structured extraction of amended terms from modification agreements, so that I can track how loan conditions change over time.

#### Acceptance Criteria

1. WHEN a document is classified as modification_agreement, THE Fact_Extractor SHALL extract the following fields for each term change: original_loan_reference, modified_field_name, original_value, new_value, effective_date, and SHALL assign a confidence score between 0.0 and 1.0 to each extracted field
2. THE Fact_Extractor SHALL support the following modified_field_name values: interest_rate, tenure_months, emi_amount, moratorium_period_months. IF a modification document contains a term change that does not map to one of the supported modified_field_name values, THEN THE Fact_Extractor SHALL skip that change and not produce a fact record for it
3. WHEN the modification agreement references an original loan by account number or agreement ID, THE Fact_Extractor SHALL extract that reference as original_loan_reference
4. WHEN a modification document contains multiple term changes, THE Fact_Extractor SHALL extract each change as a separate fact record
5. WHEN a required field (original_loan_reference, modified_field_name, original_value, new_value, or effective_date) is not present in the source document, THE Fact_Extractor SHALL record that field as "not_found" with confidence 0.0
6. THE Fact_Extractor SHALL normalize interest_rate original_value and new_value to annual percentage values, tenure and moratorium values to whole months, and emi_amount to a numeric value in the document's stated currency

### Requirement 4: Repayment Statement Fact Extraction

**User Story:** As a compliance analyst, I want each payment record extracted from repayment statements, so that I can reconcile actual payments against loan terms.

#### Acceptance Criteria

1. WHEN a document is classified as repayment_statement, THE Fact_Extractor SHALL extract each payment row containing: payment_date, amount_paid, late_fee_charged, outstanding_balance
2. THE Fact_Extractor SHALL normalize payment_date to ISO 8601 format (YYYY-MM-DD)
3. THE Fact_Extractor SHALL normalize amount_paid, late_fee_charged, and outstanding_balance to numeric values with exactly 2 decimal places in the document's stated currency
4. WHEN a repayment statement contains multiple payment rows, THE Fact_Extractor SHALL extract each row as a separate fact record and assign a 1-based sequential row_index reflecting the order of appearance in the source document
5. IF a payment row contains a payment_date that cannot be parsed into a valid calendar date, THEN THE Fact_Extractor SHALL record the payment_date field as "unparseable" with confidence 0.0 and extract the remaining fields of that row normally
6. IF a payment row contains a monetary field (amount_paid, late_fee_charged, or outstanding_balance) that is blank or non-numeric, THEN THE Fact_Extractor SHALL record that field as "not_found" with confidence 0.0 and extract the remaining fields of that row normally
7. THE Fact_Extractor SHALL assign a confidence score between 0.0 and 1.0 to each extracted field in a payment row

### Requirement 5: Source Pointer Provenance

**User Story:** As an auditor, I want every extracted fact linked to a precise location in the source document, so that I can verify any fact by navigating directly to the original text.

#### Acceptance Criteria

1. THE Source_Linker SHALL attach a Source_Pointer to every extracted fact, comprising document_version_id, page_number (for PDF) or section_id (for DOCX/text), start_offset, and end_offset. Offsets are 0-based character positions relative to the beginning of the page or section text
2. THE Source_Linker SHALL ensure that start_offset is strictly less than end_offset for every Source_Pointer
3. WHEN a Source_Pointer is resolved against the stored document text, THE Source_Linker SHALL return the exact substring from position start_offset (inclusive) to end_offset (exclusive) that was used to extract the associated fact
4. THE Source_Linker SHALL store Source_Pointers in the source_locations table with foreign key references to the claims table and document_versions table
5. FOR ALL extracted facts, resolving the Source_Pointer and re-parsing the returned substring SHALL yield the same structured value as the original extraction (round-trip property)
6. IF resolution of a Source_Pointer fails (offsets exceed the page/section text length, or the referenced document_version_id does not exist), THEN THE Source_Linker SHALL raise a SourceResolutionError with the claim_id, source_location_id, and the reason for failure

### Requirement 6: Synthetic Document Generation

**User Story:** As a developer, I want a generator that produces realistic synthetic microfinance documents with deliberate cross-document conflicts, so that I can test conflict detection and ingestion accuracy end-to-end.

#### Acceptance Criteria

1. THE Synthetic_Generator SHALL produce a pile of exactly 5 documents: at least one Loan_Agreement, at least one Modification_Agreement, and at least one Repayment_Statement
2. THE Synthetic_Generator SHALL embed exactly 2 Factual_Conflicts across the generated pile
3. WHEN generating a Factual_Conflict, THE Synthetic_Generator SHALL ensure the conflict is between a Modification_Agreement and a subsequent Repayment_Statement (e.g., modification grants a rate reduction but the repayment statement still bills at the original rate, or modification grants a moratorium but the repayment statement shows payments collected during the moratorium period)
4. THE Synthetic_Generator SHALL produce documents in at least 2 of the 3 supported formats (PDF, DOCX, plain text)
5. THE Synthetic_Generator SHALL produce documents with realistic structure: headers, clause numbering, borrower/lender names, dates within a 3-year window ending on the generation date, interest rates between 8% and 36% per annum, and monetary amounts representative of microfinance loans (principal between 5,000 and 500,000 in local currency)
6. THE Synthetic_Generator SHALL output a conflict manifest alongside the generated documents, listing for each embedded Factual_Conflict: the conflicting field name, the expected value from the Modification_Agreement, the contradicting value in the Repayment_Statement, and the document filenames involved
7. THE Synthetic_Generator SHALL ensure chronological and referential coherence across the pile: all documents in the pile SHALL share a common loan reference identifier, the Loan_Agreement date SHALL precede any Modification_Agreement effective_date, and each Modification_Agreement effective_date SHALL precede the earliest payment_date in any Repayment_Statement that reflects (or conflicts with) that modification
8. WHEN the Synthetic_Generator is invoked with an optional integer seed parameter, THE Synthetic_Generator SHALL produce identical output for the same seed value across repeated invocations

### Requirement 7: End-to-End Provenance Test

**User Story:** As a developer, I want an automated test that runs the full ingestion pipeline on the synthetic pile and verifies that every extracted fact has a valid, resolvable source pointer, so that I can catch provenance regressions.

#### Acceptance Criteria

1. WHEN the provenance test executes, THE Pipeline SHALL ingest all 5 synthetic documents and produce at least 1 extracted fact per document, completing the full ingestion within 120 seconds
2. THE provenance test SHALL assert that every extracted fact has exactly one associated Source_Pointer record in the source_locations table
3. THE provenance test SHALL assert that every Source_Pointer resolves to a non-empty substring (at least 1 character) of the source document's stored text, where end_offset does not exceed the document text length
4. THE provenance test SHALL assert that start_offset < end_offset for every Source_Pointer
5. THE provenance test SHALL assert that re-parsing the resolved substring using the same extraction logic produces a structured value identical to the originally extracted fact value (round-trip equality)
6. IF any Source_Pointer fails to resolve (offsets exceed document length or reference a non-existent document_version_id), THEN THE provenance test SHALL fail with an assertion message that includes the claim_id, the source_location_id, and the reason for failure (out-of-bounds offset or missing document_version_id)
7. IF the Pipeline returns an error for any of the 5 synthetic documents during ingestion, THEN THE provenance test SHALL fail immediately with an assertion message identifying the failed document filename and the error returned
