# Multilingual family communication engine

**Assigned build — SuperDocs Round 2.** Who it serves: education / district
communications leads. Difficulty band S2. Surfaces touched: API, templates,
multi-document, export.

Report-card comment sheets, permission slips, and district notices need to
reach families in their home language, merged with the child's and
teacher's details, with the district's layout and branding intact. This
generates each family's letter from one shared template and a shared
teacher comment bank, in whatever language that family has on file, and
produces both individual per-family PDFs and one combined print run.

## What's in here

- `family_letters.py` — the engine. Reusable, not a one-off script.
- `data/district_template.html` — one shared template with `{{merge_field}}`
  placeholders. Fictional district, fictional students, all synthetic.
- `data/comment_bank.json` — teacher comments, referenced by id from the
  roster rather than duplicated per family.
- `data/families.json` — the family roster: child, grade, teacher, home
  language, which comment applies, and whether that letter's already been
  sent.
- `output/` — real output from a real run against the live SuperDocs API:
  three languages (Spanish, Arabic, Simplified Chinese), per-family PDFs,
  one combined print-run PDF, and `RECONCILIATION_REPORT.md` proving the
  merged fields are correct rather than just asserting it.

## Run it yourself

```bash
export SUPERDOCS_API_KEY=sk_...
python family_letters.py generate                  # generates every family with status "pending"
python family_letters.py edit-comment C1 "new text" # edits the comment bank, regenerates ONLY pending letters that use it
python family_letters.py export                     # per-family + combined print-run PDFs
```

`export` needs `soffice` (LibreOffice) and `pdfunite` (poppler-utils) on
PATH; both are common Linux package-manager installs.

## What "strong" required here, and what actually happened testing it

The assignment's own bar: *"layout survives right-to-left and CJK scripts
on the same template; merged fields correct at scale with a reconciliation
report proving it; a comment-bank edit affects only pending letters and
never already-sent ones."* All three are demonstrated in `output/`, but
none of them worked on the first try, and the fixes are the actual
engineering content of this build:

1. **Merge-and-translate in one instruction is unreliable.** Asking
   SuperDocs to both fill template fields and translate in a single prompt
   left stale, untranslated placeholder text behind. Fixed by making field
   merging a deterministic Python string-replace and giving SuperDocs one
   job only: translate an already-complete document, preserving structure.
2. **RTL scripts render correctly but don't lay out correctly by default.**
   SuperDocs' translated HTML carries no direction markup (correctly, that's
   not a translation concern) but the PDF export path doesn't infer
   right-to-left paragraph alignment from a single top-level `dir="rtl"`.
   Fixed by tagging each block element explicitly before export.
3. **Comment-bank edits only reach pending letters** because that's an
   explicit status filter in `edit-comment`, not an assumption — verified by
   editing `C1` (used by both a pending and an already-sent family) and
   confirming only the pending one regenerated.

Full detail and the actual before/after evidence: `output/RECONCILIATION_REPORT.md`.

## What's not built

- OCR/parsing for source documents that arrive as scanned images rather
  than clean HTML/text.
- A real district roster integration (SIS/SFTP import) — `families.json`
  stands in for that here.
- Automatic language detection; `language_code`/`language_name` are
  explicit roster fields, matching "recorded language" in the brief rather
  than inferring it.
