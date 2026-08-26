# BUG-001: Batched section fill leaves PLACEHOLDER tokens / duplicate blocks

**Date:** 18 August 2026  
**What I did:** `generate_narrative("legal")` — upload 9-section skeleton, batched chat (cap=2) instructing SuperDocs to replace `PLACEHOLDER_TALKING_POINT_N` / `PLACEHOLDER_SPEAKER_NOTES_N` completely, then export markdown/docx.  
**Expected:** Each slide-equivalent section contains one talking point + full speaker notes; no PLACEHOLDER_* strings remain.  
**Got instead:** Several sections gained real prose **and** still retained a leftover `*Speaker notes:* PLACEHOLDER_SPEAKER_NOTES_N` (or markdown-escaped `PLACEHOLDER\_…`) block, or accumulated duplicate Talking point / Speaker notes blocks. Landed-check that only compared "text changed" falsely passed until we required placeholders to be absent.  
**How badly it blocked:** workaround found — stricter landed-check + split-retry; quality still imperfect on first pass for some sections.  
**Repro:**
1. Upload skeleton with PLACEHOLDER_* bodies for sections 1–9.
2. Chat: rewrite sections N–N+1 replacing placeholders completely.
3. Export markdown; search for `PLACEHOLDER`.
**Workaround adopted in this build:** `landed_check` fails any section still containing `placeholder_talking_point_N` / `placeholder_speaker_notes_N` (after unescaping `\_`); `chat_with_landed_check` split-retries failed sections alone. Cap=2 retained.
