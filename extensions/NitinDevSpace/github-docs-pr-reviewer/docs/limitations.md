# Limitations

This file must stay honest as the build progresses.

## Sprint 0

- No database or queue implementation yet.
- Health endpoint and config validation are available.

## Sprint 1

- GitHub webhook signature verification is implemented.
- Event routing is implemented for pull requests, issue comments, releases, and tag pushes.
- Event handlers currently return queued placeholder run keys.
- No GitHub API reads or writes yet.
- No real queue persistence yet.
- Local webhook forwarding instructions are deferred until the GitHub App is created.

## Sprint 2

- Static review is implemented for changed-file fixtures and direct runner inputs.
- The app can filter docs files and generate structured findings without live keys.
- Static Markdown review is line-based for now, not a full Markdown AST parser.
- Broken link checks are conservative because Sprint 2 does not fetch the full repository tree.
- No GitHub API reads or writes yet.
- No PR comments are posted yet.

## Sprint 3

- GitHub review publishing is implemented behind a testable client interface.
- Summary comment create/update behavior is implemented.
- Inline pull request review payload generation is implemented.
- The Octokit adapter is implemented and unit-tested with a fake Octokit object.
- The app still does not authenticate as a real GitHub App yet.
- The app still does not fetch real PR file contents yet.
- Inline comment line mapping assumes the finding line exists on the PR head side.

## Sprint 4

- SuperDocs export is isolated behind an adapter and uses the documented export endpoint; the exact account-level export response should still be verified with a real Pro key.
- Preview generation produces a local HTML artifact without credentials and stores DOCX/PDF bytes returned by SuperDocs when configured.
- The current artifact link is a filesystem path unless `PUBLIC_ARTIFACT_BASE_URL` is configured for a publicly reachable artifact host.

## Sprint 5

What the apply command does today:

- Parses `/superdocs review|preview|help|apply <finding-id>|apply all-safe` from PR comments.
- Refuses to run for a commenter without write access, and refuses commands from bots.
- Re-reads the PR's documentation files at the current head SHA and re-derives findings before touching anything.
- Applies only anchored single-line fixes, then verifies that no line other than the targeted ones changed before committing.
- Patches and verifies every affected file in memory before writing anything, so a verification failure leaves the branch untouched.
- Commits through the GitHub contents API with the blob SHA, so a branch that moved underneath us is rejected by GitHub rather than clobbered.
- Reports applied, refused, and failed outcomes in a PR comment that names the cause and the next step.

Honest limits:

- Only two rules produce machine-applicable fixes: heading-level skips and the `utilize` style term. Missing alt text, unresolved placeholders, TODO markers, suspicious links, and `click here` are advisory only, because a safe fix for them means writing prose the app cannot invent. This is deliberate: the capability is absent on those paths rather than present and unreliable.
- Fixes are single-line replacements. Multi-line and cross-file refactors are not supported.
- `apply all-safe` creates one commit per file, not one commit across all files. Single-finding apply, the graded path, is always exactly one commit. A single commit across several files needs the git tree API instead of the contents API, and that is not built yet.
- Finding IDs are derived from path, line, category, and title. If a line moves, its ID changes and the old ID is refused with a message asking for `/superdocs review`. This is safe but means an ID copied from an older commit will not apply.
- The command path is wired end to end and unit-tested against a fake GitHub client, but it has not yet been run against a real installed GitHub App, because app authentication is still Sprint 6/7 work.
- A malformed command is reported in the webhook response but does not yet post a reply comment explaining the mistake to the commenter.
- `review` and `preview` verbs parse and route, but re-running the review and regenerating the preview on demand is not wired to the command executor yet; only `apply` has an executor.

## Sprint 6

What the release document does today:

- Runs on `release.published` and skips drafts.
- Picks the most recent earlier published release as the comparison base and lists the documentation files changed since it.
- Renders release notes plus that file list into a branded document, escaping any markup embedded in the notes.
- Exports through SuperDocs when configured, and stores the same HTML locally when not.
- Attaches the document as a release asset, skipping the upload when an asset with that name already exists.
- Reports a failed attachment while keeping the generated document on disk.

Honest limits:

- The "merged PRs touching docs" section from the original plan is not built. The document lists changed documentation *files* between the two tags instead, which is derivable from the compare API without extra calls. Listing the PRs behind those files needs commit-to-PR association and was cut.
- The comparison base is the previous published release, not the previous tag. A repository that tags without releasing gets a wider diff than expected.
- Release note content is reproduced as written. The document says explicitly that it is not independently verified.
- The document is generated on release publication only. Editing a release afterwards does not regenerate it.
- Attachment idempotency is by asset name, so a regenerated document will not replace an existing asset. Replacing it would need a delete-then-upload, which is destructive and was deliberately not built.
- The whole path is tested against a fake GitHub client. It has not been run against a real published release.

## Sprint 7

- `npm run demo` is the one-command path a stranger can run.
- GitHub App authentication is implemented and gated on credentials. A missing key is a named gap, not a crash.
- A SuperDocs or filesystem failure during preview generation does not prevent the review from being posted.
- Document HTML is escaped before Markdown parsing, so a source file cannot inject markup into an artifact.
- Artifact path segments reject values that would become `.` or `..`.
- Live GitHub posting has not been exercised against a real installed app in this workspace. The adapters, the pipeline, and the demo cover the product loop; the remaining step is creating the GitHub App and pointing a webhook at the server.
