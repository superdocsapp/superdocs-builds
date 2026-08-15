# Bug ledger

## Documentation refresh script masked a failed download

- Expected: failed `curl` stops the refresh.
- Actual: PowerShell continued and printed success after a sandboxed network failure.
- Impact: stale documentation could be mistaken for refreshed documentation.
- Workaround: reran with network access and verified file size and timestamp.
- Fix: the script now downloads to a temporary file, checks curl's exit code and size, and replaces the cache only after success.

No live SuperDocs product issue was observed because no credential was available and no live request was made.
