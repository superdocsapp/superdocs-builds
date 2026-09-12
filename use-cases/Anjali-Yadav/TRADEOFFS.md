# Honest trade-offs and residual risk

## Shared principle
These three builds are intentionally evidence-first and explicit about uncertainty. That makes them stronger than shallow “AI summarization” demos, but it also means they are conservative in what they claim.

## Build 1: Multi-hop QA
### Strengths
- explicit hop list makes the answer auditable
- grounded evidence is checked against exact source documents
- no fake answer when evidence is missing

### Residue
- retrieval quality still matters; a poor document set will reduce answer quality
- a user must confirm whether the question is genuinely multi-document enough to justify the workflow

## Build 2: Citation verification
### Strengths
- independent entailment check catches unsupported citations that look valid at first glance
- per-citation findings are more honest than a single claim-level verdict

### Residue
- paraphrased claims can be harder to validate without a human reading the source within context
- a citation may be semantically relevant but still not clearly support the exact sentence as written

## Build 3: Material-change analysis
### Strengths
- mechanical diff prevents the model from guessing at surface changes
- formatting is stripped away before material analysis begins
- cross-reference renumbering is treated as substantive by design

### Residue
- production legal review still requires a human reviewer to decide whether the impact is material in context
- large rewrites can produce too much candidate noise for one LLM pass, so chunking is still required

## General residue across all builds
- live API behavior must still be verified against the current SuperDocs API contract
- if the platform already provides a built-in document search or multi-document session mechanism, it should be used instead of re-implementing the same capability locally
- any unsupported or ambiguous result should be surfaced clearly, not silently suppressed
