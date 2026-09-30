# Recorded SuperDocs responses

Captured from the **live API on 2026-08-10** by `scripts/probe_superdocs.py`,
not hand-written from the docs. `respx` replays them at the httpx transport
layer, so the offline test suite exercises the real client against real shapes.

Regenerate with `make probe-all`. Findings are written up in
[`docs/SUPERDOCS_CONTRACT.md`](../../docs/SUPERDOCS_CONTRACT.md).

| File | Pins |
|---|---|
| `01_whoami.json` | Quota shape. `account_id` scrubbed to zeros |
| `02_upload.json` | **`document_id` is `"doc_primary"`** — a session slot, not durable. Also shows the parsed HTML arriving with the upload |
| `02b_session_documents.json` | Where `durable_document_id` actually lives |
| `03_document_detail.json` | The free, non-billable `structure` block |
| `04_document_html.json` | Per-block HTML with `data-chunk-id` |
| `05_chat_async.json` | Job accepted |
| `06_job.json` | **`pending_changes` as a real ARRAY** — the documented double-parse does not apply to polling |
| `07_approve.json` | Per-change batch approval |
| `08_structure_after.json` | `block_count` unchanged after an edit |
| `10_redaction_structure.json` | `parts[]` — headers and footers as addressable blocks |
| `11_redaction_changes.json` | Seven `edit` operations, including header and footer |

## The three `.docx` files earn their place

They are the assertions of the export verifier, and two of them must behave in
opposite ways:

| File | Must |
|---|---|
| `12_redacted.docx` | **Pass** — multi-line address, `<br/>` join, header and footer all clean |
| `13_hidden_export.docx` | **Fail** — PII intact inside tracked changes and a comment. Proves export scrubs nothing on its own |
| `14_hidden_redacted.docx` | **Pass** — the same document after redaction, 9/9 strings gone, `w:del` and `comments.xml` structurally intact |

A verifier that cannot reject `13` is not a verifier.

## Not kept

Regenerable outputs were removed rather than committed: the T2.2 split parts
(the split test produces them and the measurement is in the contract doc), a
duplicate copy of the document HTML, a subset of `06_job.json`, and a plain
re-export. `make probe-all` writes throwaway binaries to `.probe/`, which is
gitignored.
