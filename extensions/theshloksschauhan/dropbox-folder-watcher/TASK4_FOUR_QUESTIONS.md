# Four questions (submission form)

## 1. What broke?

Using SuperDocs: the first instruction in a fresh session can hang or fail until things warm up (as the task email warned). Proposed-change payloads arrive as a JSON string inside JSON; missing the second parse yields empty diffs with every field `undefined`. Large documents sit with no progress for minutes — still processing, not a crash. Exports do not cost operations, which is easy to miss when budgeting a loop.

Using Dropbox: events fire on half-written uploads; a content-hash debounce is required. Write-back of our own file would retrigger the loop without a path + hash registry.

Using our own first build: the worker originally auto-approved in the same run, which made the console gate fake. Preview was a UI toggle that did not block spend. Those are fixed: the worker stops at `REVIEW_PENDING`; preview is a chokepoint in the SuperDocs client.

I have not filed these through the in-app bug button yet; I will, because reported bugs score.

## 2. If you ran SuperDocs, what one number would you watch every morning?

**Share of proposed edits that a human resolves (approve or reject) within 24 hours.**

Generating diffs is not the product. The product is edits that land, gated, in the real file. If that number falls, either the model is noisy, review is too expensive, or the loop is writing without a person. I would pair it with a secondary: operations spent per *committed* export, so spend without write-back shows up.

## 3. Five features next, in order — what I would drop — what I would fix now

1. Per-client Dropbox OAuth (real shared-folder permissions).
2. Webhook-first scan with polling as backup.
3. Item-level reject of individual proposed hunks, if SuperDocs ever exposes it; until then, clearer job-level diffs.
4. Slack/email when a job hits `REVIEW_PENDING`.
5. Per-folder ops dashboard (budget used vs cap).

**Drop:** the in-console “seed sample drop” once a live Dropbox demo is the default path.

**Fix immediately:** any regression of the double JSON parse; empty review cards destroy trust. Also: say “still processing” in the console when SuperDocs is silent for >30s.

## 4. How would day-to-day engineering and GTM run themselves?

Loops, not headcount:

- **Product:** every in-app bug report becomes a ticket with “did / expected / got / blocked / file.” An agent triages duplicates against docs.superdocs.app. Humans only re-open severity.
- **Engineering:** CI runs keyless tests on every PR. Staging has a golden corpus. A nightly job posts failed runs, p95 latency, and ops spend. Schema and billing changes stay human-gated.
- **GTM:** a watched folder of public case studies; SuperDocs drafts a one-page note; a human approves before anything is sent. No candidate or employee ever emails prospects on the company’s behalf unless that is their job.
- **What breaks first:** silent quality drift (diffs look fine, lawyers disagree), not CPU. The check is sampled human review of committed exports, not more dashboards.
