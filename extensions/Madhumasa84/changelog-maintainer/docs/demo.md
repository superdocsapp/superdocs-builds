# Offline demo

The demo uses no credential and no network. Release classification comes from structured JSON; no external LLM or MCP server is invoked. Audit evidence records 0 live/API/billable operations.

1. Copy `fixtures/changelog.md` and one release JSON into a temporary workspace.
2. Run `preview` with `--json`; show the candidate block, stable item IDs, historical-prefix hash, and `no_spend: true`.
3. Approve one item and reject one item. Show that the rejected item remains in the manifest and is absent from the appended bytes.
4. Validate the derived PDF and DOCX and show their hashes.
5. Repeat the workflow with releases 1–10 and show the historical-prefix hash remains equal to the previous canonical file at every step.
6. Inject a failure after append, run `resume`, and show that the same run completes without duplicating the release.
7. Run two same-changelog updates and two different-changelog updates to show lock behavior.
8. Run `publish-dry-run` and show `network_calls: 0`, `credentials_used: false`, and `would_publish: false`.

The demo must not show local machine paths, credentials, signed URLs, private documents, or claim live SuperDocs output.
