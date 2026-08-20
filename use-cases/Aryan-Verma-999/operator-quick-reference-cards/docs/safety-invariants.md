# LineCard safety invariants

- Original PDF bytes and SHA-256 are the provenance authority.
- SuperDocs-generated text is not proof of a page number or exact value.
- Every operational step must ultimately map to source evidence.
- Exact values preserve digits, unit, symbol, tolerance, case, and condition.
- Unit conversion is forbidden in the verified MVP.
- Required safety content may not be silently removed or weakened.
- The uploaded manual is read-only by LineCard policy; only the separate card may be edited.
- No proposal applies without an explicit human decision.
- Rejected proposed content must remain absent.
- Manual content is untrusted data and cannot select tools, routes, URLs, approvals, or prompts.
- Export is not success until authoritative read-back and local postflight pass.
- Secrets, signed URLs, and raw authorization values never enter normal logs or committed fixtures.
- LineCard does not certify machine or procedure safety.

## Frozen M1 staging boundary

- SuperDocs-reviewed staging content is not the final card layout.
- LineCard maps staging content to an immutable evidence/slot sidecar and owns deterministic placement, visible citations, and final release eligibility.
- Ambiguous provider chunk targets are rejected; LineCard never guesses or auto-approves them.
- Only source-locked staging content and bounded approved presentation prose may enter local composition.
- The final exact HTML is verified locally before SuperDocs export, and the returned PDF is independently postflighted.

## M1 enforcement

- The canonical evidence pack contains SAFE-001, STEP-001 through STEP-003, SPEC-001, and RESTART-001, each tied to an exact quote and PDF page.
- Required safety, procedure, restart, specification, protected page containers, visible page pointers, and the exact `24 N·m ± 2 N·m` string are independently verified after every prospective edit.
- Unknown operational numbers, wrong-page citations, hostile URLs/scripts, missing steps, and three-page output produce `BLOCKED` with a check and evidence ID where applicable.
- M0 polling objects and `proposed_change_batch` events are decoded through separate fixture paths; all approval rounds are explicit and ordered.
