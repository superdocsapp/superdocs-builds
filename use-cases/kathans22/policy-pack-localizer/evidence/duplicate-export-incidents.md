# Bug report: `export_document` intermittently returns the document duplicated —
# sometimes recoverably, sometimes with genuinely conflicting content

Filed against: SuperDocs `export_document` tool (MCP), `format=markdown`, called repeatedly
against the same `session_id` (once per annex batch, to verify it actually landed, plus a
final export — see `packs.py`'s "verify the document, not the response" design).

Found while building: `use-cases/kathans22/policy-pack-localizer` (Task 2, Build 1).

Severity: **not blocking for the shipped build** — the code now detects both variants and
either self-heals (identical-duplicate case) or quarantines cleanly (conflicting case) rather
than shipping a corrupted pack. This report is the follow-up to
`evidence/superdocs-batch-limit-report.md`: that report covers `chat`'s edits being unreliable;
this one covers `export_document` itself intermittently returning a corrupted document, a
separate defect discovered afterward while re-running the rollout from a clean state.

## What broke

Calling `export_document(session_id=..., format="markdown")` more than once against the same
session — which the build does by design, to verify each annex batch actually landed before
moving to the next — can return the document with every section duplicated. Two distinct
sub-cases were observed:

**A. Duplicated, but every copy is byte-identical.** The whole document (already correctly
edited) comes back repeated N times in a row, still legible, still structurally valid, just
N× longer. This was the first form found, documented in `PROGRESS.md`'s repair notes: 9
sections became 72 headings across three export calls in one session — consistent with the
corruption compounding roughly 2× on each further export call against an already-affected
session (2³ = 8 copies after 3 exports).

**B. Duplicated, and the copies genuinely disagree with each other.** The more severe form,
found while re-running a full 5-country rollout from a freshly reset state (`core_version: 1`,
`out/` and `state/` wiped). Two countries failed in the same run:

- **Kenya** — export came back with 218 headings for a 9-section document (some sections
  repeated over 20 times), and critically, not every copy matched: some carried the correct
  annex content, others still carried the master's unedited placeholder text, and one copy of
  section 6 had escalation content spliced into it instead of reporting-channel content —
  i.e. content from a *different* section entirely.
- **Brazil** — same failure shape, 130 headings, in the same rollout run.

Real error surfaced to the caller (from `packs.py`'s quarantine path, quoted verbatim):

```
KE pack export carried conflicting duplicate section content on every one of 2 attempts and
could not be safely verified: section number(s) [4, 6, 7, 8, 9] appear more than once with
different content in this document — it may have been corrupted by an export call. Fix: this
document cannot be safely parsed as one policy pack; inspect the raw export.. Quarantined at
/app/out/_quarantine/KE/policy-pack.md.
```

Both countries had already been generated correctly at least once earlier in the build (see
`PROGRESS.md` Phase 4), so this is not a "never works" defect — it's intermittent, and it can
recur on a country that previously succeeded.

## What we expected

That `export_document` is a read of the session's current document state and therefore
idempotent: calling it twice in a row with no edit in between should return the same content
both times. Neither sub-case is consistent with that — sub-case A returns the same content
duplicated; sub-case B returns content that has actually diverged between "copies" that
shouldn't exist at all.

## What we did about it

**For sub-case A (identical duplicates):** fixed at the parse layer, not the retry layer.
`sections.parse_sections` (the one place every caller in the codebase parses a document) now
compares every copy of a repeated section number; if all copies are byte-identical, it
silently collapses to the first occurrence instead of raising. This closes the whole class for
the benign case with zero extra SuperDocs calls, and it's what let a persistently-duplicating
session still ship a correct pack (`tests/test_packs.py::test_generate_pack_recovers_when_every_export_stays_verbatim_duplicated`).

Also cut the final-export retry loop from 3 attempts to 2 (`_MAX_FINAL_EXPORT_ATTEMPTS`):
live evidence showed retrying more exports against an already-corrupted session doesn't
reliably clear it and can compound the duplication further — so a bounded single retry
(for a genuine transient race) followed by quarantine is more honest than looping and hoping.

**For sub-case B (genuine conflicts):** the code correctly refuses to guess which copy is
right and quarantines the pack (`PackIntegrityError`, never shipped, run does not report
success — the `out/_quarantine/{code}/` file is preserved for inspection). This is by design,
not a gap: silently picking a copy would be exactly the kind of "success message that doesn't
mean what it claims" the build's own integrity model exists to prevent.

**Manual recovery**, applied live to both Kenya and Brazil to unblock the demo: abandon the
affected session, start a fresh one, and instead of re-sending the same multi-section batch
that triggered the corruption, apply each annex section as its own single-section `chat` call,
verifying the export after every one. When a single-section edit still corrupted a heading
(observed on section 9 for both countries — the AI wrote the new content into the `<h2>`
chunk instead of the `<p>` body chunk, exactly the "wrong-chunk" defect logged in
`PROGRESS.md` Phase 4), the reliable fix was the same one documented there: build the fully
correct document locally from the archived master + `_SLOT_RENDERERS`, and re-upload it
verbatim via `upload_document_base64` into the same session — a load, not an AI edit, so it's
free (`usage` absent from the response) and deterministic. Both countries verified clean
against their `core_version: 1` lock afterward.

## Why this isn't fixed at the code level entirely

Sub-case B has no safe automated recovery: once a session has produced genuinely conflicting
duplicate content, there is no way to know from inside that session which copy (if any) is
correct without an external source of truth. The build has one — the archived master and the
per-country render functions — which is exactly why the manual recovery above works. Building
that into the automated retry path (detect conflict → rebuild locally → re-upload verbatim →
re-verify, all without a human) is the natural next step and is listed as follow-up work; it
was done by hand in this session because the demo needed to be unblocked immediately, not
because it can't be automated.

## Pattern across both bug reports

Every defect in this file and in `superdocs-batch-limit-report.md` shares one root cause: a
success-shaped response (or, here, a successful-looking export) is not proof of the document's
actual state. The build's whole design — verify the export, never the response text or the
call succeeding — is what caught all of these live rather than shipping a silently-corrupted
pack.
