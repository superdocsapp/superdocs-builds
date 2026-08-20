# Decisions

This file records build decisions so future sprints do not drift.

## 2026-08-11 - Use A Dedicated Task Folder

Decision: keep the GitHub Docs PR Reviewer in `assigned-builds/github-docs-pr-reviewer`.

Reason: the workspace will contain multiple SuperDocs tasks, and the root should stay organized.

## 2026-08-11 - Use Node.js And TypeScript For This Assigned Build

Decision: use Node.js, TypeScript, and Fastify for the GitHub App backend.

Reason: GitHub App tooling is strongest in the Node ecosystem, and TypeScript gives strong webhook payload and app configuration safety. The separate shared engineer task can still use Python/FastAPI if we build it later.

## 2026-08-11 - Start With Deterministic Review Before AI Review

Decision: Sprint 1 and Sprint 2 should make the app useful without a live SuperDocs key.

Reason: tests must run without live keys, and deterministic checks give us reliable fallback behavior when external APIs fail.

## 2026-08-11 - Implement Webhook Routing Before GitHub API Writes

Decision: Sprint 1 verifies GitHub webhook signatures and routes supported events, but does not call GitHub APIs yet.

Reason: this keeps the first integration boundary testable without credentials. Sprint 2 can focus on PR scanning and static review logic before Sprint 3 posts comments.

## 2026-08-11 - Keep Sprint 2 Review Keyless And Conservative

Decision: Sprint 2 uses deterministic Markdown checks and does not call GitHub or SuperDocs.

Reason: the employer explicitly values tests that run without live keys. Static review also gives us a reliable fallback when SuperDocs or GitHub API calls fail later.

## 2026-08-11 - Do Not Overclaim Broken Link Proof Yet

Decision: relative links are marked as needing verification only when suspicious, instead of claiming they are definitely broken.

Reason: without a full repository tree from GitHub, the app cannot honestly prove every relative link target exists.

## 2026-08-11 - Publish Through A GitHub Client Interface

Decision: Sprint 3 introduces a `GitHubReviewClient` interface plus an Octokit adapter instead of directly coupling review logic to Octokit.

Reason: publishing behavior can be tested without live credentials, and Sprint 4/Sprint 5 can reuse the same boundary for preview links and apply commands.

## 2026-08-18 - Fixes Are Anchored To The Line Text They Were Derived From

Decision: an autofix carries the exact line text the review saw (`before`) plus the replacement (`after`), and applying it refuses unless the current line still matches `before`.

Reason: line numbers drift when a branch moves, and writing to a line number we no longer recognise is how an automated committer corrupts someone's work. Anchoring on content makes drift a refusal instead of damage. The apply runner additionally diffs the whole file afterwards and refuses to commit if any line outside the targeted ones changed, so surgical precision is proven rather than asserted.

## 2026-08-18 - Only Mechanical Fixes Get An Autofix

Decision: only heading-level skips and the `utilize` style term produce applicable fixes. Missing alt text, placeholders, TODO markers, suspicious links, and `click here` stay advisory.

Reason: the remaining rules need prose a human has to write. Generating it would mean inventing document content, which is exactly what the brief says not to do. A capability that is honestly absent on a path beats one that is present and wrong.

## 2026-08-18 - The Server Starts Without Credentials

Decision: missing GitHub App credentials or a SuperDocs key is a named, degraded mode, not a startup failure.

Reason: a stranger has to be able to clone and run this. The product loop is visible through `npm run demo`. The live path is a configuration step, not a prerequisite for understanding the build.

## 2026-08-18 - A Preview Failure Does Not Cancel The Review

Decision: if SuperDocs export or local artifact storage fails, the pipeline still posts the review, without a preview link.

Reason: a review without a preview is useful. A preview without a review is not. The failed stage is recorded with its error, so the run does not claim the preview happened.

## 2026-08-18 - Source Documents And Release Notes Are Escaped Before Markdown Parsing

Decision: `markdownToSafeHtml` escapes HTML before parsing Markdown, and both the PR preview and the release document use it.

Reason: document content and release notes are untrusted data this app reports on. Parsing them straight through `marked` would let raw HTML in a source file become live markup in an artifact we hand back. Escaping first makes embedded markup show up as visible text, which is the correct reading: it is content to display, not instructions or markup to execute. Fixing it in the shared helper covers both surfaces rather than the one that surfaced it.

## 2026-08-18 - Artifact Path Segments Reject All-Dot Values

Decision: `safeSegment` maps any value consisting only of dots to `unknown`, and strips leading dots.

Reason: the original sanitiser allowed dots so that filenames could keep their extensions, which meant a tag literally named `..` survived as a real traversal segment. A release tag is attacker-controllable in a forked workflow, so this was a genuine path-traversal hole rather than a theoretical one. The test asserts the resolved artifact path stays inside the artifacts directory for several hostile tag names, instead of just checking for a substring.

## 2026-08-18 - Release Documents List Changed Files, Not Merged PRs

Decision: the release document lists documentation files changed since the previous published release, rather than the merged pull requests behind them.

Reason: the file list comes free from the compare API, while associating commits with pull requests needs extra calls and heuristics. The narrower claim is fully supportable from one request, and the document names what it could not determine.

## 2026-08-18 - Patch Everything In Memory Before Writing Anything

Decision: the apply runner patches and verifies every affected file in memory first, and only then starts committing.

Reason: the first version interleaved verification and committing, so a multi-file `all-safe` run could commit one file and then refuse on the next while reporting that nothing had been committed. That report would have been false. Planning first means a verification failure leaves the branch untouched, and the only remaining partial case is GitHub rejecting a commit mid-way, which is reported explicitly with the files already committed named.

## 2026-08-18 - Commands Must Lead The Comment

Decision: a `/superdocs` command is only recognised when it is the first non-empty line of the comment. Quoted commands, fenced commands, and commands mentioned mid-sentence are ignored, as are comments from bots.

Reason: docs PRs discuss the commands themselves, and this app's own review comments list them. Treating a mention as an instruction would let document or comment text drive the app, and would risk a bot-to-bot loop.

## 2026-08-18 - Applied And Refused Replies Use Different Markers

Decision: successful applies write a `superdocs-applied:<key>:<sha>` marker; refusals write `superdocs-apply-refused:<key>:<sha>:<reason>`.

Reason: a single shared marker made a retry after a refusal look like work already done. Separate markers keep both properties: an apply never commits twice for the same head SHA, and a repeated impossible command is explained once rather than on every retry.

## 2026-08-18 - Refuse To Commit To Fork Head Branches

Decision: if a PR's head branch lives in a different repository from the base, the apply command refuses and explains why.

Reason: a GitHub App installed on the base repository generally cannot push to a contributor's fork. Attempting it produces a confusing GitHub error; refusing up front names the real constraint and points at the manual path.

## 2026-08-11 - Summary Comments Are Idempotent Per Head SHA

Decision: summary comments include an invisible marker containing the PR head SHA.

Reason: reprocessing the same commit should update the existing bot summary rather than posting duplicate comments. A new head SHA gets its own review trail.
