# Detailed Section-by-Section Audit Checklists

Use this granular checklist when conducting a multi-contributor editorial pass before final export.

---

## 1. Title & Abstract Checklist
- [ ] Title contains fewer than 18 words and avoids uncalibrated acronyms.
- [ ] Abstract contains the 5 fundamental beats:
  1. *Context/Hook*: Why this problem matters now.
  2. *Deficiency*: What existing approaches fail to solve.
  3. *Core Contribution*: What specific method or system is proposed.
  4. *Key Quantified Results*: Primary benchmark numbers with statistical significance.
  5. *Broader Impact*: Practical implications for the discipline.

---

## 2. Introduction & Related Work Checklist
- [ ] The problem formulation is established by page 2.
- [ ] Explicit bulleted list of 3–4 novel contributions at the end of Section 1.
- [ ] Related work is structured by conceptual themes, not merely chronological listing.
- [ ] Differentiators are articulated objectively without derogatory characterizations of prior art.

---

## 3. Methodology & Mathematical Formulation Checklist
- [ ] All variables defined immediately before or after their first mathematical appearance.
- [ ] Dimensionality of vectors, matrices, and tensors clearly annotated (e.g. $\mathbf{x} \in \mathbb{R}^{d \times k}$).
- [ ] Algorithm pseudo-code block includes explicit inputs, outputs, time complexity, and space complexity.
- [ ] Assumptions regarding data distributions and stationarity stated explicitly.

---

## 4. Empirical Evaluation & Results Checklist
- [ ] Baselines represent current state-of-the-art models, not obsolete historical benchmarks.
- [ ] Results tables bold the best performing metric and underline the second-best.
- [ ] Ablation studies isolate the individual performance contribution of each architectural component.
- [ ] Qualitative error analysis / failure case study included.

---

## 5. Discussion, Limitations & Ethical Considerations Checklist
- [ ] Stated limitations cover compute requirements, domain transferability, and data biases.
- [ ] Compute budget table specifies total GPU hours, carbon estimate, and hardware configurations.
- [ ] Data provenance and human subject approvals (IRB / ethics review IDs) explicitly disclosed.
