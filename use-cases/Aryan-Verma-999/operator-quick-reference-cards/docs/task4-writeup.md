# Task 4 — LineCard

**Problem.** OEM manuals contain the authoritative safety instructions and operating values, but operators need a short job aid beside a machine. A summary can silently drop a warning, change a number, or cite the wrong page.

**User.** Maintenance leads, operators, field service teams, and safety reviewers who need a reviewed, printable card for one task.

**Solution.** LineCard freezes a manual, retrieves evidence from separated sections, creates a typed plan, and composes an exact two-page card. Every required step, critical value, safety instruction, restart check, and page pointer is independently verified before export.

**Why SuperDocs.** SuperDocs supplies durable documents, semantic retrieval, asynchronous HITL proposals, review transport, read-back, and exact-HTML PDF export. LineCard supplies source identity, evidence, layout, and release gates.

**Trust mechanism and hard part.** A changed `24 N·m ± 2 N·m`, missing isolation warning, unsupported number, wrong citation, hostile markup, ambiguous target, or impossible layout blocks. LineCard intentionally refuses to approve an edit if SuperDocs cannot provide a deterministic synchronized target identity. Corrected live checks found zero matches between synchronized targets and proposals (8/6 in recovery and 8/31 in a fresh run). No decision or export was attempted; this is documented as a provider defect.

**Result and next step.** LC-100 and AX-200 paths, verifier, flow diagram, batch mode, recovery, accessibility, metrics, and M4 image/export proof are tested. Next: resolve the provider chunk contract, rerun bounded M1 certification, then measure production-scale latency and memory.
