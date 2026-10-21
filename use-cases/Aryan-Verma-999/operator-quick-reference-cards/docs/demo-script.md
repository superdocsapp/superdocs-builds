# Three-minute LineCard demo

**0:00–0:20 — Problem and source.** Show the synthetic ~400-page LC-100 OEM manual and say: “An operator needs a short card, but the manual remains the authority.” Ask for **clear jam on infeed**.

**0:20–0:45 — Retrieval.** Show hits from separated manual sections: safety on one page, procedure on another, specification on page 24, and restart/interlock on a later page. Explain that task-specific retrieval returns evidence, not free-form instructions.

**0:45–1:05 — Exact evidence.** Show `24 N·m ± 2 N·m` with its PDF page pointer and the SAFE/STEP/RESTART evidence IDs. Every required step has a visible source reference.

**1:05–1:25 — Card.** Show the deterministic two-page HTML/PDF: safety gate, ordered procedure, evidence-backed flow diagram, exact specification, restart check, source index, and subordinate-card disclaimer.

**1:25–1:45 — Sabotage.** Change `24 N·m ± 2 N·m` to `26 N·m ± 2 N·m`; show the independent verifier returning `BLOCKED`. Restore the value. Briefly show the same result for removed safety wording, unsupported numeric value, or wrong citation.

**1:45–2:00 — Verified export.** Show the passing verification report and the public-safe two-page export artifact. Say: “The export is allowed only after source checks, layout checks, and PDF postflight pass.”

**2:00–2:20 — Batch.** Open the 3-card batch manifest. Point out separate tasks, evidence sets, statuses, retries, budgets, and blocked-sibling behavior. Mention the materially different AX-200 manual.

**2:20–2:45 — SuperDocs boundary.** Show `docs/superdocs-live-bug-report.md`. Use this exact line: “SuperDocs can propose edits; LineCard refuses to release an operator card unless every critical claim still matches the manual.” Explain that corrected evidence used the documented `document_sync.content` HTML and still found zero matching chunk IDs: 8/6 in recovery and 8/31 in a fresh live run, with no approval and no export. Never fake a live approval sequence.

**2:45–3:00 — Close.** Show the architecture diagram and run `make demo` / `make test`. Close with: “LineCard is locally verified and submission-ready, while live M1 certification remains blocked by a verified SuperDocs chunk-ID contract defect.”
