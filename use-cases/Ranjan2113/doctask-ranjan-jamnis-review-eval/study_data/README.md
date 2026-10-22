# study_data/

Published deliberately. What each file is, and what has been redacted.

| File | Contents |
| --- | --- |
| `batches.json` | The corpus: per-batch changes plus the pre-registered answer key and its SHA-256 digest. Contains ground truth — **do not open this before reviewing.** |
| `confirmations.json` | The confirmed labels, with who confirmed each and when (GT-7). |
| `label_review_doc*.json` | Per-document diffs with proposed labels, the input to the confirmation step. Also contains ground truth. |
| `ops_ledger.jsonl` | Every SuperDocs operation charged, appended after each call. Entries noted `ESTIMATED` are conservative assumptions where the server reported no usage block. |
| `raw_events.jsonl` | The append-only decision log for the reported run (reviewer `R2`). |
| `assignment.json` | Which reviewer saw which condition on which batch. |
| `pilot_run.log`, `study_run.log` | Console output from the corpus builds, kept as provenance. |
| `discarded/` | Pilot run 1, excluded from all analysis. Retained so PROTOCOL.md Amendment 2 can be checked rather than taken on trust. Must never be merged into results. |

## Redactions

**SuperDocs job UUIDs are replaced with `job-redacted-NN` placeholders**
throughout `batches.json`, `ops_ledger.jsonl` and the run logs. They identified
real jobs on the author's SuperDocs account and are not needed to understand or
reproduce anything here.

The mapping is stable and one-to-one: the same job carries the same placeholder
everywhere, so provenance survives. `batch_doc04`'s three placeholders still
show it took three calls, and the ledger still ties each operation to the call
that spent it.

Nothing else is redacted. `change_id` and `chunk_id` values are unmodified —
they are content identifiers that the analysis joins on, and rewriting them
would break the link between decisions and ground truth.

## Not published

`study_data/checkpoints/` is gitignored: raw API payloads, regenerable only by
re-spending operations, and local processing state rather than a deliverable.
