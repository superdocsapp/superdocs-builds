# BUG-001: Multi-file citation in a section heading gets silently truncated, dropping the closing paren

**Date:** 22 August 2026
**What I did:** `compliance --generate --clients CL-02 --today 2026-08-22` — plan → coverage → `generateCompliancePack` (one batched `chat/async` call drafting 5 sections) → `verifyCompliancePack` via the free `GET /v1/documents/{id}` structure read. The RIA-FEE-01 section's coverage status was INCONSISTENT with two evidence files, so `canonicalSectionHeading()` built the instructed h2 as `"Fee disclosure current and consistent with the agreement — Inconsistent (client-onboarding-notes.md, fee-schedule-change-2026.md)"` (~133 chars) and the model was told to reproduce it verbatim.
**Expected:** All 5 planned section headings land verbatim, each carrying its full citation parenthetical exactly as instructed.
**Got instead:** `structure.headings` for that section came back as:
`Fee disclosure current and consistent with the agreement — Inconsistent (client-onboarding-notes.md, fee-schedule-change`
— cut off mid-filename, no closing paren, `-2026.md)` missing entirely. The other 4 sections (shorter headings, single-file citations) landed intact in the same draft.
**How badly it blocked:** Not silent — `verifyCompliancePack`'s citation check (`/\(.+\)/` requires a matching open+close paren on the actual heading text) correctly failed this section as an uncited claim, exactly as designed. But it meant any status needing more than one cited file was unreliable, which would have made INCONSISTENT findings — the plant this exact client/requirement exists to demonstrate — undemonstrable.
**Repro:**
1. Build a coverage entry with 2+ evidence files for one client/requirement.
2. Generate the section heading as `{title} — {Status} (file1.md, file2.md)` (~130+ chars).
3. Draft the pack via `chat/async`, then read back `structure.headings` for that document — the tail of the heading is gone.
**Workaround adopted:** `canonicalSectionHeading()` in `src/compliance/coverage.ts` now cites exactly one representative evidence file (`entry.evidence[0].file`) instead of joining every file the coverage check touched, keeping every heading well under the apparent length threshold. Retested CL-02 live after the fix — the same section rendered in full (`... Inconsistent (client-onboarding-notes.md)`) and verification passed. Root cause (an exact length limit, and whether it's the model or the document platform enforcing it) wasn't isolated further — out of scope for a two-day build — but the fix holds regardless of where the limit actually lives.
