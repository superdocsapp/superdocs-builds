# Bug ledger

## Documentation refresh script masked a failed download

- Expected: failed `curl` stops the refresh.
- Actual: PowerShell continued and printed success after a sandboxed network failure.
- Impact: stale documentation could be mistaken for refreshed documentation.
- Workaround: reran with network access and verified file size and timestamp.
- Fix: the script now downloads to a temporary file, checks curl's exit code and size, and replaces the cache only after success.

## Null pending changes during live polling

- Action: submitted the first synthetic async edit and polled its durable job.
- Expected: processing responses normalize to an empty proposal list until review proposals exist.
- Actual: the live API returned `metadata.pending_changes: null`; the adapter attempted to iterate it and raised `TypeError`.
- Impact: the first live run stopped during polling after edit submission; no approval or export was attempted.
- Ownership: Project A adapter bug; the API response is compatible with the nullable OpenAPI schema.
- Fix: normalize null to an empty list and cover the processing response with a regression test.
- Resolution: covered by regression and verified against the resumed live job.

## Post-approval state and multi-batch review

- Action: submitted item decisions and polled the durable job.
- Expected: completion or a clearly new proposal batch.
- Actual: normal processing exceeded the original 180-second bound and the API briefly repeated `awaiting_approval` with already-decided proposal IDs before later batches.
- Impact: the client timed out at 95% and initially misclassified stale state as a new batch.
- Ownership: Project A lifecycle assumption; the durable API job remained recoverable.
- Fix: five-minute bounded post-approval polling, same-ID stale-state suppression, and support for up to five genuine review batches.

## SuperDocs structural normalization

- Action: independently verified the completed live HTML.
- Expected: application-specific section/table markers would remain present.
- Actual: SuperDocs preserved standard `<section>`, `<table>`, all `data-chunk-id` values, and every protected fact, but removed redundant `data-agreement-section` and `data-payment-schedule` attributes.
- Impact: the verifier falsely blocked a factually correct document and correctly prevented export until diagnosed.
- Ownership: Project A verifier compatibility assumption, not factual output corruption.
- Fix: use preserved chunk IDs as the structural fallback and accept a table inside the schedule chunk; the exact live document now passes with zero findings.
