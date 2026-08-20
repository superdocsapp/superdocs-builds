# Bugs found — Canva → Long-Form Document build

12 issues found during development, each with a clear scenario, what was expected vs. what happened, and impact. Several were root-caused with real investigation, not just observed once.

---

## 1. PDF text extraction returns character-spaced text

**Where:** Our own code (pypdf reading Canva's PDF export)
**Scenario:** Extracting text from a Canva-exported PDF using pypdf.
**Expected:** "August 17, 2026"
**Actual:** "A u g u s t 1 7 , 2 0 2 6" — a space inserted between every character.
**Cause:** Canva places PDF text character-by-character rather than as flowing text runs; pypdf's gap-based extraction inserts a space at every detected gap.
**Fixed:** Yes — a post-processing function collapses single-character gaps while preserving genuine word boundaries (detected via double-spacing in the source).

## 2. SuperDocs DOCX export drops inline heading color

**Scenario:** Sent HTML with `<h2 style="color:#2f4f33">`, exported the same session as both `.docx` and `.pdf`.
**Expected:** Both formats show the brand green heading color.
**Actual:** PDF correctly renders green headings. DOCX renders the same headings in Word's default blue heading-style color, discarding the inline color entirely.
**Impact:** Real fidelity loss for any use case (like this one) needing brand colors to survive into Word specifically.
**Status:** Reported to SuperDocs, not something fixable on our end (server-side HTML→DOCX conversion).

## 3. Inconsistent image sizing across SuperDocs export formats

**Scenario:** Same session, same embedded hero image, exported as `.docx` and `.pdf`.
**Expected:** Consistent image sizing in both formats.
**Actual:** PDF export shrinks the image to a small corner thumbnail; DOCX export renders it full-page-width.
**Impact:** Visual quality significantly degraded in one format depending on which is used.
**Status:** Reported to SuperDocs.

## 4. SuperDocs templates carry only the primary brand color reliably

**Scenario:** Uploaded a template document demonstrating a full brand style (primary/secondary/tertiary colors, table styling, blockquote styling). Asked a fresh session to draft new content "using my brand template," with zero explicit color instructions.
**Expected:** New content matches the full template's visual system.
**Actual:** The primary color (`#2f4f33`) was picked up correctly and consistently. Secondary and tertiary colors, and the template's specific visual patterns (underlined headings, bordered callouts), were not — the AI introduced a different, unrelated visual pattern for new sections.
**Impact:** Templates alone are not sufficient for full brand consistency; explicit per-request color instructions proved more reliable (see finding below).

## 5. Sections silently duplicated across multi-turn document generation

**Scenario:** Built a 6-section document across 6 sequential `/v1/chat` calls in one session, each adding one new named section, with the brand palette stated only once on turn 1.
**Expected:** 6 unique sections.
**Actual:** 4 of the 5 sections added via follow-up turns were duplicated — created twice under the same heading, each time with different body text. Reproduced independently on two separate, fully isolated test runs, same ~4/5 duplication rate both times.
**Impact:** Significant — this is the core failure mode for exactly the kind of long-document, multi-turn use case this build's card describes ("keep the visual system consistent from page 1 to page 40").
**Mitigation built on our side:** A duplicate-detection quality gate (regex-based heading-text comparison) that flags this before export, so it's caught rather than silently shipped.

## 6. `approval_mode='ask_every_time'` activates inconsistently

**Scenario:** Sent equivalent requests via `/v1/chat/async` with `approval_mode='ask_every_time'` across multiple test runs.
**Expected:** Every request pauses at `status=awaiting_approval` for human review, per the documented HITL flow.
**Actual:** Sometimes correctly pauses for review; other times goes straight from `in_progress` to `completed`, auto-applying the change with zero review step. Observed a run where all 3 of 3 parallel jobs skipped review entirely.
**Impact:** Cannot be relied upon as a genuine human-in-the-loop gate in its current state.

## 7. Content proposed during a genuine review pause was placeholder text, not real content

**Scenario:** A job correctly reached `awaiting_approval` with real pending changes to review.
**Expected:** Proposed content is genuine generated material.
**Actual:** The proposed `new_html` itself contained meta/placeholder text: *"Here we will expand the 'About Us' copy from your flyer into an energetic, brand-aligned section..."* — literal placeholder, not actual content, even before any approval decision was made.
**Impact:** The async+review generation path appears to produce lower-quality output independent of the separate activation-reliability issue (#6) — two distinct problems in the same feature.
**Comparison:** The plain `/v1/chat` path was tested identically across 9+ generations throughout this build and never once produced placeholder content.

## 8. `/approve` endpoint requires an undocumented `job_id` field

**Scenario:** Called `POST /v1/chat/{session_id}/approve` with `{"approved": true}` (per the documented single-change shape).
**Expected:** `200 OK`.
**Actual:** `422` — `{"detail":[{"type":"missing","loc":["body","job_id"],"msg":"Field required"}]}`. The endpoint's documented parameters don't mention `job_id` as required.
**Fixed:** Yes, once discovered — `job_id` is now always included in the approve request body.

## 9. `cancel_job`'s suggested fix doesn't work for its own error state

**Scenario:** Received a `409 session_busy` error (*"The AI is still working on a previous request... cancel it with cancel_job"*) for a job stuck in `awaiting_approval`. Called `cancel_job` on it, as explicitly suggested by the error message itself.
**Expected:** Job cancelled.
**Actual:** `400` — `{"detail":"Job cannot be cancelled"}`. Cross-referencing SuperDocs' own docs confirms `cancel_job` only works on `pending`/`processing` jobs, not `awaiting_approval` — directly contradicting the `409` error's own `suggested_action`.
**Real fix found:** Resolve the stuck job through the approve endpoint instead (reject all pending changes), not `cancel_job`.

## 10. Seeded document content not reliably available to the immediately-following instruction

**Scenario:** Called `/v1/chat` to seed a session with `document_html`, then immediately called `/v1/chat` again with the expansion instruction, same session.
**Expected:** The second call sees and expands the seeded content.
**Actual:** Sometimes the AI responds *"I don't see any text or file attached to your message"* — the seed wasn't yet visible to the very next call, despite both calls succeeding individually.
**Cause (likely):** A timing/indexing race condition between the seed write and the next read.
**Fixed (workaround):** Stopped relying on the seed being reliably read — the actual copy is now embedded directly inside the generation instruction itself, removing the dependency on any server-side timing.

## 11. Canva PNG export returns misleading `permission_denied` on orientation mismatch

**Scenario:** Requested a PNG export at fixed portrait dimensions (2480×3508) for a landscape-oriented Canva design.
**Expected:** Either a successful export, or a clear dimension/validation error.
**Actual:** `403 permission_denied` — `"Not allowed to access design with id ..."` — indistinguishable from an actual access-control failure.
**Investigation:** Ruled out team/ownership mismatch (identical owner and team IDs confirmed via `GET /designs/{id}` across a working and a failing design) and "never opened in Canva's UI" (edited and saved directly in Canva, still failed). Created three fresh test designs varying only orientation; only the landscape one failed — conclusively isolating orientation as the actual cause.
**Fixed:** Yes — the app now detects a design's orientation (via its thumbnail's width/height) before requesting a print-resolution export, and swaps the requested width/height accordingly.
**Worth flagging to Canva:** the error code (`permission_denied`) is genuinely misleading for what is actually a dimension/orientation mismatch, and cost significant debugging time before the real cause was isolated.

## 12. `html_bundle` export not supported for this design's type

**Scenario:** Requested `format.type: "html_bundle"` for the primary test design.
**Expected:** An HTML export containing text + CSS/style structure.
**Actual:** `400 bad_request_body` — `"html_bundle export not supported for this design type."`**Resolution:** Confirmed via `GET /designs/{id}/export-formats` that only `pdf`, `jpg`, `png`, `pptx`, `gif`, `mp4` are supported for this design type. Switched to PDF (text/layout) + PNG (visual palette) as a substitute — a real, logged scope decision, not a silent workaround.