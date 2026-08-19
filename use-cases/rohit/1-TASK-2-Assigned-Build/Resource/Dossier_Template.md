# The Pre-Submission Paper Checklist
*A Simple Pre-Flight Checklist for High-Stakes Scientific & Technical Publications*

> **Author / Affiliation Disclosure**: *Created by Rohit as a free open resource for the scientific research community. Built using SuperDocs (a document-native AI editing environment). You are free to copy, modify, and distribute this checklist without attribution.*

---

## Document Overview & Pre-Flight Metadata

| Metadata Field | Specification / Value |
|---|---|
| **Working Title** | `[Insert Target Manuscript / Proposal Title]` |
| **Primary Corresponding Author** | `[Lead PI / Author Role]` |
| **Target Journal / Granting Agency** | `[e.g. Nature Machine Intelligence / NIH R01 / NSF CISE]` |
| **Submission Deadline** | `[Date & Timezone]` |
| **Manuscript Word Count / Page Ceiling** | `[e.g. 8,500 words / 20 pages max]` |
| **Primary Code / Dataset Repository** | `[DOI / Zenodo / GitHub Link]` |

---

## 1. Abstract Checker

*Goal: Ensure that every factual claim made in the Abstract is explicitly supported by empirical data in the Results section and not contradicted in the Discussion.*

| Abstract Claim Statement | Supporting Result Section / Table | Statistical Significance / Effect Size | Status (Verified / Needs Revision) |
|---|---|---|---|
| *[Paste Claim 1]* | | | `[ ]` |
| *[Paste Claim 2]* | | | `[ ]` |
| *[Paste Claim 3]* | | | `[ ]` |

---

## 2. Number Tracker (Parameter Sync)

*Goal: Prevent parameter drift across independently written sections (e.g., hyperparameter changes in Section 3 that were forgotten in Section 5 or the Abstract).*

```markdown
<!-- SUPERDOCS MULTI-SECTION RECONCILIATION PROMPT -->
@document-target: [Section 3.1 Experimental Setup, Section 4 Results, Section 6 Compute Budget]
Instruction:
Verify that all batch sizes, learning rates, dataset sample counts (N), and compute cluster specifications match across all three sections.
Flag any discrepancy with inline review comments.
```

| Parameter Name | Abstract Reference | Methodology (Sec 3) | Results (Sec 4) | Appendix / Compute | Status |
|---|---|---|---|---|---|
| **Sample Size ($N$)** | | | | | `[ ]` |
| **Learning Rate ($\eta$)** | | | | | `[ ]` |
| **Hardware Topology** | | | | | `[ ]` |

---

## 3. Bibliography & Citation Integrity Audit

1. **DOI Resolution**: Every citation must resolve to an active DOI or permanent arXiv ID.
2. **Prior Art Fairness**: Ensure top 3 competing frameworks from 2024–2026 are cited in Section 2 (Related Work) with fair baseline comparisons.
3. **No Phantom Citations**: Verify that all bracketed reference keys `[1..N]` correspond to an existing entry in the References section.

---

## 4. Compliance Check (Data & Ethics)

*Goal: Ensure all modern open-science and ethical mandates required by top-tier journals (e.g., Nature, NeurIPS, IEEE) are met before submission.*

- [ ] **Data Availability Statement (DAS)** explicitly links to a public repository (e.g., Zenodo, GitHub, OSF).
- [ ] **Ethics Committee / IRB Approval Number** is explicitly cited in the Methodology section (or an exemption statement is provided).
- [ ] **Code & Weights**: All custom code, pre-trained weights, and training hyperparameters are included in the supplementary material or a linked repository.
- [ ] **Funding & Conflicts of Interest**: All grant numbers and potential conflicts are declared in the acknowledgements.

---

## 5. Reviewer Prep Checklist

- [ ] **Methodological Reproducibility**:
  - [ ] Are random seeds and hardware environments explicitly documented?
  - [ ] Is the data pre-processing pipeline described with sufficient detail for an independent lab to reproduce?
- [ ] **Statistical Rigor**:
  - [ ] Are error bars (SD or SEM) defined in all figure captions?
  - [ ] Have appropriate multiple testing corrections (e.g., Bonferroni, FDR) been applied?
- [ ] **Clarity & Flow**:
  - [ ] Are all abbreviations defined on first use?
  - [ ] Do mathematical symbols adhere strictly to standardized notation throughout all equations?
