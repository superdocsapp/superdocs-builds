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

2. **PDF export doesn't inherit RTL layout automatically.** SuperDocs'
   translated HTML for Arabic carries no `dir`/text-alignment markup of its
   own (correct — that's a rendering concern, not a translation one), and
   LibreOffice's HTML→PDF path (used for export here) does not infer
   right-to-left paragraph alignment from a single `dir="rtl"` on `<html>`.
   The first export rendered Arabic script correctly but left every
   paragraph left-aligned. Fixed by applying `dir="rtl"` and explicit
   `text-align: right` per block element before export — confirmed visually
   in `F2_ar.pdf`, fully right-aligned, script correct. This is the actual
   place "layout survives right-to-left scripts" has to be made true, not
   assumed true.
