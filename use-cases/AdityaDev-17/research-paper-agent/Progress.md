# Progress log

Tracks build phases against the original checklist. See `BUGS.md` for issues hit along the way.

## Phase 1 — Data model & the proof mechanism ✅
`Paper` / `Section` / `Citation` / `Source` / `RunLog` defined. Content-hash mechanism on `Section` proven with a dedicated test (`test_section_hash.py`) — revising one section leaves every other section's hash byte-identical.

## Phase 2 — Retrieval index ✅
FAISS-backed `RetrievalIndex`, chunk provenance (`chunk_id → source_id`) verified via test with a fake embedder before any real API cost.

## Phase 3 — Outline agent ✅
Fixed 8-section skeleton (Abstract → References), loaded into a real SuperDocs session in one call.

## Phase 4 — Section drafting loop ✅
Retrieval-grounded drafting: every claim carries its supporting chunk ID at generation time. Hallucinated citations (chunk IDs not in the retrieved set) are rejected loudly, not silently accepted.

## Phase 5 — Supervisor verifier ✅
LLM-as-judge grounding check per citation. Proven against the card's own bar: a deliberately planted unsupported claim is caught and flagged, real claims pass.

## Phase 6 — Targeted revision loop ✅
Only flagged citations get rewritten; untouched citations and sections are provably byte-identical before/after (hash-diff proof).

## Phase 7 — Export gate ✅
Export refuses to run while any section is unverified. HTML and PDF export confirmed working end to end; Word (.docx) export removed after a local file-locking issue (see BUGS.md #7).

## Real integration (OpenAI + SuperDocs MCP) ✅
- `OpenAIClient`: real embeddings + chat completions, cost/token tracking built in.
- `SuperDocsMCPClient`: real MCP client against the live SuperDocs server — handles the real chat/session/approval model (not the granular API originally assumed), including auto-approving HITL-gated edits and polling jobs to completion.
- First full end-to-end run (real topic, real sources, real document, real export) succeeded.

## Streamlit app ✅
- Source upload: `.txt`, `.pdf`, `.docx`.
- Topic inferred from uploaded sources (not user-typed) via one LLM call.
- Live checklist showing section-by-section drafting progress.
- Tabs always visible: Draft (combined, editable full-paper view with save), Run Log, Model & Cost, Evaluation, Export (HTML/PDF).

## Evaluation metrics ✅
Implemented and wired into the Evaluation tab: citation support rate, revision rate, source coverage, citation density, and a section-redundancy check (embedding similarity) that directly targets the repetition issue observed in an early test run.

## Remaining ✅
- **Phase 9 — reproducibility run.** Run the app on a second, genuinely different topic + a richer source set (4-6 varied files), to demonstrate the pipeline isn't tuned to one example and to get a demo-quality output without the early repetition issue.
- Sanity-check the Evaluation tab's numbers on that second run.
- Project README (see `README.md`).
- Demo video/clip.
- Final secrets scan (`git status --ignored`) before pushing.
- Open the PR.