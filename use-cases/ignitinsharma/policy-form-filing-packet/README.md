# Policy-Form Filing Packet Builder

A use case that turns a changed insurance policy form into a complete
regulator-facing filing packet: new form, redline vs. the previously approved
form, filing memorandum (one-to-one with the redline), side-by-side comparison,
state-specific cover letter, and a checklist gate — all with the form's
typography, clause numbering, and layout preserved through the entire round trip.

Built for the SuperDocs assigned-build round entirely through the **SuperDocs
MCP server** (multi-document sessions, human-in-the-loop Review gate, template
library, fidelity-preserving export). All documents are fictional.

## What it does

1. Two inputs: `HO-3 Policy Form - Approved Version` and `HO-3 Policy Form - Proposed Version`
   (fictional insurer "Meridian Mutual Insurance Company", Form No. HO-3 (04/24),
   Georgia font, real `.docx` typing so typography is *provably* preserved).
2. **Redline** — `chat_async` with `approval_mode: ask_every_time` marks strike-through /
   bold-underline spans and edge notes. The Review gate caught and rejected a
   mangled first proposal (deleted clause bodies, invented wording); per-change
   feedback produced the correct revision, which was approved (HITL exercised).
3. **Filing memorandum** — one entry per redline change: old text → new text → rationale.
4. **Side-by-side** comparison table.
5. **Cover letter** — generated from a template in the SuperDocs template library
   (`[STATE]`, `[REGULATOR_NAME]`, `[STATE_LAW]`, `[EFFECTIVE_DATE]` slots), filled
   for a New York filing. State variations live in data, not forked code.
6. **Checklist gate** — 10 required items each stamped against live account state;
   everything must PASS before export.
7. **Export** — everything exported as both `.docx` and `.pdf`; the redline was
   verified after export: exactly 8 style-marked runs survived the round trip.

## Files

- `README.md` — this file
- `screenshots/` — UI / editor evidence: approved form, proposed form, redline, approvals, cover letter, checklist, side-by-side
- `files/` — final packet PDFs (approved, new form, redline, memo, cover letter, checklist, side-by-side)

## How to run

This build was executed via the SuperDocs MCP server (streamable HTTP):

```
# connect the MCP server to any MCP client
url: https://api.superdocs.app/mcp
headers: Authorization: Bearer sk_<your-key>   # get at https://use.superdocs.app -> Settings -> API Keys
```

Steps (see the private repo's `task2-assigned-build/` for the full playbook):

1. Upload the approved and proposed `.docx` forms (files `upload_document_base64`).
2. `chat_async` on the proposed form, `approval_mode: "ask_every_time"`,
   with a redline instruction that names the same spans and the rule to preserve
   Georgia font / clause numbering / "Form No." series.
3. Review the proposed changes at the gate; reject with per-change feedback
   if wrong, approve when correct.
4. Compose the memo (chat), side-by-side table, and cover letter from the template
   library; stamp the checklist against the actual documents.
5. `export_document` as docx and pdf; verify styled runs in the exported redline.

Cost observed: 1 operation on the free plan (500/month) — the rest is upload,
template, chat-created documents, and exports; verification was free.

## SuperDocs features used

- MCP server (`chat`, `chat_async`, `approve_change`, `upload_document_base64`,
  `export_document`, `list_documents`, `rename_document`, `archive_document`,
  `upload_template_base64`, `list_session_documents`, `get_job`)
- Human-in-the-loop Review gate (three changes rejected → revised → approved)
- Template library (state cover letter)
- Multi-format export (docx + pdf)
- Fidelity-preserving edits (typography and numbering intact across the round trip)

## Credits

Built by Nitin Sharma for the SuperDocs growth/GTM engineering round.