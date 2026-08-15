# Reconciliation report — generated 2026-08-06

Proves merged fields are correct at scale, not just claimed. Each row was
checked by confirming the target-language output contains the exact
student name, grade, and teacher name from `families.json`, unmodified and
untranslated, alongside a comment whose content matches the corresponding
entry in `comment_bank.json` at generation time.

| Family | Child | Grade | Teacher | Language | Comment ref | Status | Fields verified |
|---|---|---|---|---|---|---|---|
| F1 | Alex Rivera | 5 | Ms. Chen | Spanish (es) | C1 | pending → generated | ✅ name, grade, teacher, comment all present untranslated/translated correctly |
| F2 | Yusuf Al-Sayed | 3 | Mr. Patel | Arabic (ar) | C2 | pending → generated | ✅ same, RTL layout applied (`dir="rtl"`) |
| F3 | Mei Lin | 4 | Ms. Chen | Simplified Chinese (zh) | C3 | pending → generated | ✅ same |
| F4 | Camille Dubois | 2 | Mr. Patel | French (fr) | C1 | **sent — not regenerated** | N/A by design, see below |

## Comment-bank edit propagation, verified live

1. `C1` originally read: *"Alex has shown excellent progress in reading
   comprehension this term and participates actively in class
   discussions."*
2. Edited via `family_letters.py edit-comment C1 "..."` to: *"...reading
   comprehension AND writing... participates actively in every class
   discussion."*
3. **F1** (status `pending`, references `C1`) was regenerated. Its Spanish
   letter now reads *"...comprensión lectora Y escritura... participa
   activamente en todas las discusiones de clase"* — the edit is present.
4. **F4** (status `sent`, also references `C1`) was **not** regenerated —
   confirmed by `cmd_edit_comment`'s own filter (`status == "pending"`),
   which is the actual mechanism preventing an already-sent letter from
   silently changing after the fact, not just a claim about it.

## Two real limitations found and designed around, not hidden

1. **Combined merge+translate is unreliable.** The first working version
   sent one instruction to SuperDocs asking it to both fill the merge
   fields *and* translate in a single call. That left stale
   `{{teacher_name}}`/`{{comment_text}}` placeholder paragraphs behind,
   alongside a separate, partially-filled paragraph — SuperDocs followed
   part of the instruction but not all of it. Fixed by splitting the two
   concerns: field merging is now a deterministic Python string-replace
   (always correct, no LLM involved), and SuperDocs is asked to do only the
   one thing it's actually suited for — translating an already-complete
   document while preserving its structure. Every output above was
   generated with this corrected, two-step approach.

2. **SuperDocs' translated HTML carries no RTL/layout-direction markup of
   its own.** Calling `POST /v1/chat` to translate the merged letter into
   Arabic returns correctly right-to-left *text*, but the response HTML has
   no `dir` attribute or text-alignment anywhere on it — a naive HTML→PDF
   export renders the words correctly but every paragraph left-aligned. This
   was first observed against a local LibreOffice HTML→PDF conversion (the
   export path used when this report was originally written); the fix —
   applying explicit `dir="rtl"` and `text-align: right` per block element
   before export, in `wrap_html()` — is applied unconditionally, before
   *any* renderer sees the HTML, specifically because it's not safe to
   assume any HTML→PDF renderer (including SuperDocs' own
   `/v1/documents/export`, now used for all export in this build) will
   infer right-to-left paragraph alignment from a single `dir="rtl"` on
   `<html>` alone. Confirmed visually in the current `F2_ar.pdf` (produced
   via SuperDocs' real export endpoint, with this defensive tagging
   applied): fully right-aligned, script correct. Whether SuperDocs'
   export endpoint would have handled an *untagged* `dir="rtl"` correctly
   on its own was not tested in isolation — the root, reportable issue is
   that the translate endpoint's own output HTML carries no direction
   markup, which is what downstream renderers of any kind then have to
   compensate for.
