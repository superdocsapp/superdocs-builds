# Ideal Customer Scoring Rubric

## 1. Purpose

This artifact provides a reproducible account-scoring model for identifying the strongest SuperDocs prospects among document-intensive businesses. It is designed as a growth and revenue-operations research deliverable, not as a list of current customers.

The goal is to rank companies based on observable evidence that they have repeated, document-heavy operational workflows that are likely to create measurable value from document reconciliation, exception processing, and workflow automation.

## 2. SuperDocs ICP hypothesis

The strongest SuperDocs prospects are companies that:

- operate large volumes of recurring documents
- have routine document contradictions, exceptions, or version mismatches
- manage multiple counterparties or approval chains
- depend on those workflows for risk, compliance, operations, or revenue
- have enough operational scale to justify a material return on workflow automation

The strongest matches are therefore not simply large companies; they are companies where document complexity and business criticality align with the document-reconciliation value proposition of SuperDocs.

## 3. Scoring methodology

The rubric totals 100 points and uses five criteria. Each criterion is scored on a 0 to 4 scale, and the weighted points are calculated as:

weighted points = (raw score / 4) x criterion weight

To avoid artificial clustering, the raw scoring was calibrated against evidence quality and workflow specificity rather than by assigning the same broad pattern to every comparable company. Companies with the clearest public evidence of recurring high-volume contradiction work received comparatively higher raw scores, while weaker or more generic workflows were scored lower even when the company was still relevant.

The criteria and weights are:

Each criterion is scored on a 0-4 raw scale, and the CSV stores the weighted points earned under that criterion. The raw scale is used to make the rubric reproducible; the final dataset uses weighted points so the totals are additive and easy to audit.

1. Reconciliation / contradiction fit — 30 points
   - Definition: How often the company faces document mismatch, discrepancy, and exception-handling work.
   - Scale: 0 = minimal mismatch risk; 1 = occasional exceptions; 2 = recurring working-level discrepancies; 3 = repeated high-volume exceptions; 4 = central, high-frequency contradiction management.
   - Evidence: loan covenant schedules, project payment applications, claims paperwork, trade-letter-of-credit exceptions, title exceptions, lease and CAM reconciliations, or similar operational examples.

2. Document volume / intensity — 20 points
   - Definition: How much document throughput and decision-making is tied to recurring paperwork.
   - Scale: 0 = low volume; 1 = moderate recurring volume; 2 = material recurring volume; 3 = high volume across multiple teams or subsidiaries; 4 = very high volume with dense document dependence.
   - Evidence: portfolio size, transaction counts, large program portfolio, recurring claim volumes, or large project pipelines.

3. Recurring / incremental document activity — 20 points
   - Definition: Whether the workflow is ongoing rather than one-off.
   - Scale: 0 = episodic; 1 = occasional; 2 = recurring monthly or quarterly; 3 = consistent recurring operational pattern; 4 = near-continuous document churn.
   - Evidence: recurring financing cycles, contract renewals, project billings, claim cycles, lease roll-ups, or study-document updates.

4. Business-line relevance / buyer clarity — 15 points
   - Definition: Whether the activity sits within a clear buyer function and core business line.
   - Scale: 0 = peripheral workflow; 1 = secondary process; 2 = operationally relevant; 3 = material business-unit process; 4 = central to revenue, risk, or compliance.
   - Evidence: business-unit descriptions, portfolio-management functions, project controls, claims operations, trade finance, or title underwriting.

5. Operational complexity / evidence strength — 15 points
   - Definition: Whether the company demonstrates multi-party, multi-system, or highly fragmented operational complexity and whether the public evidence is strong enough to score confidence.
   - Scale: 0 = low complexity and weak evidence; 1 = moderate complexity; 2 = material complexity; 3 = strong multi-party complexity with good public evidence; 4 = highly fragmented and well-documented process complexity.
   - Evidence: official company strategies, investor presentations, portfolio descriptions, and public operating documentation.

These five weighted criteria were selected because they are observable, tied to value creation, and sufficiently independent from each other. They focus on process fit rather than marketing popularity or generic company size.

## 4. Criteria considered and discarded

### Criteria considered and discarded

1. Company size alone
   - Why it initially appeared useful: larger companies often process more documents.
   - Why it was rejected: size is a poor proxy for fit and can bias toward large diversified firms that are not document-intensive in the relevant workflow.
   - Assessment: subjective and redundant with document volume and operational complexity.

2. Brand recognition
   - Why it initially appeared useful: iconic brands often have large operations.
   - Why it was rejected: brand name is not evidence of document-reconciliation pain.
   - Assessment: highly subjective and not commercially meaningful.

3. Geographic footprint
   - Why it initially appeared useful: international operations often increase document complexity.
   - Why it was rejected: geography can matter, but it is a secondary factor and not a direct indicator of reconciliation burden.
   - Assessment: sometimes relevant, but too indirect and difficult to verify consistently.

4. AI-readiness or digital maturity
   - Why it initially appeared useful: companies with better software stacks might be easier prospects.
   - Why it was rejected: digital maturity is not a direct measure of need; the workflow pain should drive the score, not software readiness.
   - Assessment: subjective, hard to verify, and potentially biased toward companies with better public narratives.

5. Revenue or valuation size
   - Why it initially appeared useful: larger revenue suggests a bigger operational burden.
   - Why it was rejected: revenue is often broad and not specific to the document-intensive process being scored.
   - Assessment: difficult to tie to the exact workflow and prone to conflating company scale with process relevance.

The final rubric intentionally avoids these proxies and instead measures observable operational patterns directly connected to document-heavy execution risk.

## 5. Account universe

The 80-company universe was selected to balance the strongest SuperDocs document-heavy use cases identified in earlier research, especially:

- private credit covenant monitoring
- trade finance letter-of-credit discrepancy review
- construction pay-app and change-order reconciliation
- claims TPA reconciliation
- CRE lease and CAM reconciliation
- renewable project-development reconciliation
- title underwriting reconciliation
- clinical-trial protocol consistency
- aviation MRO and compliance tracking
- general logistics and document-heavy operational flows

The universe includes both top-fit and lower-fit accounts to make the scoring model useful for ICP work. This is deliberately not a list of only obviously ideal companies; it includes medium-fit and lower-fit companies to show where document-heavy workflows are weaker or more generic.

## 6. Scoring process

Another researcher can reproduce the scoring model using the same process:

1. Review the company public materials.
2. Confirm the company has a relevant document-heavy workflow.
3. Score each of the five criteria on the 0 to 4 scale.
4. Convert to weighted points using the formula above.
5. Sum the five weighted criterion scores to derive the total.
6. Record the evidence and rationale in the dataset.
7. Use the same evidence standard: only official company pages, investor presentations, annual reports, public filings, and credible public industry sources.

The evidence standard is intentionally strict. This list does not claim a company “definitely needs SuperDocs.” It only records observable facts that connect the company’s business model to recurring document-intensive work.

## 7. Top 10 accounts

The highest-scoring accounts are the strongest document-heavy matches for the SuperDocs use case and are concentrated in core reconciliation-heavy sectors such as construction, finance, insurance, and clinical operations. The scores are not identical because the raw scoring reflects different evidence strength, workflow intensity, and operational specificity.

1. Turner Construction — 96.2 — large project-document complexity with recurring billing and change-order reconciliation.
2. NextEra Energy — 96.2 — major renewable portfolio with repeated project, contract, and intercompany document reconciliation.
3. IQVIA — 96.2 — large clinical-trial ecosystem with protocol, site, and regulatory-document exceptions.
4. HSBC — 96.2 — high-intensity trade-finance operations with recurring LC discrepancy review.
5. Chubb — 96.2 — large claim volumes and repeated policy-document review across multiple lines.
6. Boeing — 96.2 — aerospace maintenance and technical-record complexity across major programs.
7. Apollo Global Management — 96.2 — large private-credit portfolio with recurring covenant and borrower-document review.
8. Ørsted — 92.4 — major renewable project administration with dense documentation across project development.
9. Standard Chartered — 92.4 — large trade-finance and documentary processing environment.
10. RTX — 92.4 — substantial aerospace compliance and technical-document workflow intensity.

## 8. Bottom 10 accounts

The lowest-scoring accounts are still legitimate document-heavy businesses, but they rank lower because their workflow is less clearly tied to high-contrast, exception-reliant document reconciliation or because the public evidence is narrower and more generic.

1. Alliant National Title Insurance Company — 50.0 — meaningful title workflow, but smaller operational scale and thinner public evidence.
2. Commonwealth Land Title — 50.0 — title-related operations exist, but the business footprint is smaller and less central to high-volume document exceptions.
3. GEODIS — 50.0 — logistics paperwork is material, but the workflow is less aligned with contract discrepancy and exception-heavy reconciliation.
4. J.B. Hunt — 50.0 — large shipping operations create paperwork, but less direct overlap with the strongest SuperDocs use cases.
5. New York Community Bancorp — 50.0 — general banking footprint with some credit-document activity, but less specialized private-credit workflow intensity.
6. Ryder — 50.0 — sizable logistics operations, but weaker direct evidence of contradiction-heavy workflow on the public record.
7. SL Green Realty — 50.0 — recurring lease administration exists, but the portfolio is narrower and less intense than the top CRE operators.
8. C.H. Robinson — 62.5 — large logistics and document flows exist, but they are less directly tied to the high-risk discrepancy scenarios in this rubric.
9. ENGIE North America — 62.5 — renewable-document work is relevant, but the public evidence is less operationally specific than the strongest renewable operators.
10. Realty Income — 62.5 — lease administration is relevant, but the evidence remains more finance- and ownership-centric than operational reconciliation-centric.

## 9. Vertical distribution

The dataset is balanced across 10 document-heavy verticals, with exactly 8 companies in each group:

- Private credit & lending — 8
- Trade finance — 8
- Construction & infrastructure — 8
- Insurance & claims — 8
- Commercial real estate — 8
- Renewable energy — 8
- Title & real-estate services — 8
- Clinical research & healthcare — 8
- Aviation & aerospace — 8
- Logistics & document-heavy operations — 8

## 10. Limitations

This scoring model is intentionally transparent about uncertainty.

- Public materials vary in their level of operational and document-detail disclosure.
- Some sectors are easier to verify than others.
- The rubric favors direct evidence and observable workflow fit over soft judgment.
- This is not a market-share or true-demand model; it is an ICP-fit model.
- The list is company-level only and does not include individuals or contact details.

Confidence is therefore recorded as High, Medium, or Low to avoid overstating certainty.

## 11. Data

The final scored list lives here:

- [data/scored_accounts.csv](data/scored_accounts.csv)

This dataset includes exactly 80 companies. It contains the scoring decomposition, evidence, rationale, and confidence for each account.

The dataset is meant for research, prospecting, and ICP modeling. It does not imply that any of these companies are current SuperDocs customers or that they are necessarily buying the solution.
