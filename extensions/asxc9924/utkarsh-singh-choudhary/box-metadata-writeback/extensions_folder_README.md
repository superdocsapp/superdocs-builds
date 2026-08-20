# Box Workflow App — Metadata Write-Back

Built for the SuperDocs task by UTK.

**Assigned build (S3):** enterprise content manager running Box as the
system of record uploads or amends a document. This app classifies it,
extracts key terms, drafts a companion document when the document class
needs one, normalizes it to a retention-approved template via SuperDocs,
and writes structured fields back into the file's Box metadata template
— which then drives Box's own retention, search, and workflow rules.

Full source, architecture, and write-up live in the private Task 1
repository (invited separately, per the brief). This folder is the
pointer the brief asks for: a summary, a screenshot, and a link back.

## What strong looks like, and how this build gets there

- **Metadata is populated accurately, or left empty — never guessed.**
  Every field the pipeline writes traces back to something the source
  document actually stated; anything the model can't support stays out
  of the metadata template entirely rather than being defaulted or
  invented.
- **Governance labels and legal holds are never overridden.** Enforced
  at two independent layers: the extraction pipeline never maps
  arbitrary model output onto a governance-protected key in the first
  place, and Box's own metadata-write boundary refuses those keys no
  matter what's passed to it — proven against the worst case (an
  extraction model complying with an embedded document instruction to
  try to write them), not just the ordinary case.
- **Processing is idempotent per file version**, survives concurrent
  runs on the same file, and every field the pipeline didn't touch on a
  reprocess is proven byte-identical to what it was before — not just
  absent from the change log.
- **A killed run resumes from the last completed stage, not from
  scratch.** Stage-level checkpointing means a process killed mid-run
  never redoes SuperDocs calls that already succeeded — proven across
  two real separate OS processes, one hard-killed mid-run, sharing one
  persisted checkpoint file.
- **Runs unmodified on a second, independent document batch** — a
  different vendor, a different document mix, different label formats
  — which is how a real classification bug was found and fixed rather
  than just claimed handled.
- 111/111 offline tests passing, no live key required; a real SuperDocs
  API client and a real Box API client are both implemented alongside
  the fakes used for testing.

## Screenshot

![Box metadata write-back demo](.docs/screenshots)

*(A run of `make demo-scenario` — five documents processed, one field
held for human review and approved, and the resulting Box metadata
audit trail.)*


