# superdocsr

Review-gated AI editing for research papers, from R.

Render your paper, ask [SuperDocs](https://use.superdocs.app) for a targeted
edit, look at exactly what it proposes, approve the parts you agree with, and
export the result. Nothing reaches the document until you name the changes you
accept.

Built for the SuperDocs engineer task by Aditya Meshram.

```r
library(superdocsr)

doc <- sd_upload("manuscript.docx")
job <- sd_wait(sd_edit(doc, "Replace vague intensifiers with the reported statistics."))

changes <- sd_changes(job)
changes
#> <sd_changes> 2 proposed change(s) on session paper-2026
#>
#> 1. [edit] ch_1
#>    why: Replaced an intensifier with the reported statistic
#>    -   The effect was very significant.
#>    +   The effect was significant (p = 0.03).
#>
#> 2. [delete] ch_2
#>    why: Removed a causal claim the data does not support
#>    -   This clearly proves the mechanism.
#>
#> Nothing is applied until sd_approve() names the ids you accept.

job <- sd_approve(job, "ch_1")
job <- sd_deny(job, "ch_2", feedback = "Keep the sentence; soften it instead of cutting it.")
sd_export(sd_wait(job), "docx", "manuscript-revised.docx")
```

Or the whole thing in one call, from the `.Rmd`:

```r
sd_knit(
  "paper.Rmd",
  "Tighten the discussion; keep every citation and number exactly as written.",
  export_path = "paper-revised.docx"
)
```

## Install

```r
# install.packages("remotes")
remotes::install_github("superdocsapp/superdocs-builds", subdir = "extensions/superdocsr")
```

Then put your key somewhere that is not your code. `usethis::edit_r_environ()`
opens the right file:

```
SUPERDOCS_API_KEY=sk_your_key_here
```

Get a key from Settings > API Keys at [use.superdocs.app](https://use.superdocs.app).

## Why the gate

An AI that edits your manuscript is useful right up to the moment it changes
something you did not want changed. In a paper that is not cosmetic: a
rewritten hedge becomes an overclaim, a "tightened" result becomes a different
result, and neither is obvious three drafts later.

So `sd_edit()` defaults to `approval_mode = "ask_every_time"`, and
`sd_approve()` has no default for `change_ids`. There is no
approve-everything switch. To accept a whole batch you write it out:

```r
sd_approve(job, sd_changes(job)$change_id)
```

`sd_edit(async = FALSE)` cannot pause for review, so it refuses to run unless
you also pass `approval_mode = "approve_all"` -- the unreviewed path exists,
but you have to ask for it twice.

## The API surface

| Function | What it does | Endpoint |
| --- | --- | --- |
| `sd_client()` | Key, base URL, budget, transport | -- |
| `sd_verify_key()` | Confirm an `sk_` key works | `GET /v1/sessions` |
| `sd_upload()` | Load a file as the session's document | `POST /v1/documents/upload` |
| `sd_edit()` | Start a review-gated AI edit | `POST /v1/chat/async` |
| `sd_wait()` | Poll with backoff to a stopping point | `GET /v1/jobs/{job_id}` |
| `sd_changes()` | Read the proposed changes | (from the job payload) |
| `sd_approve()` / `sd_deny()` | Decide, change by change | `POST /v1/chat/{session_id}/approve` |
| `sd_continue()` | Answer a large-edit continue prompt | `POST /v1/chat/{session_id}/continue` |
| `sd_cancel()` | Stop a running job | `POST /v1/jobs/{job_id}/cancel` |
| `sd_export()` | Write the document to disk | `POST /v1/documents/export` |
| `sd_knit()` | Render an `.Rmd`, then all of the above | -- |

Endpoints and payload shapes follow the published OpenAPI spec at
`https://docs.superdocs.app/openapi.json` and the guides at
[docs.superdocs.app](https://docs.superdocs.app). Nothing here is guessed.

## Three things that bite integrators

**Proposed changes need a second JSON parse.** Batched changes arrive inside
`metadata.intermediate_responses` with the payload in a `content` field that is
itself a JSON-encoded string. Parse once and `content` is a character scalar;
every field you read off it is empty. `sd_changes()` makes the second
`jsonlite::fromJSON()` call, which is the difference between a populated table
and a table of `NA`s. There is a regression test for exactly this.

**The approve endpoint needs a top-level `approved` field**, even when every
entry in `changes` carries its own. Omitting it is a 422 with an unhelpful
message. `sd_approve()` always sends it.

**Silence is not failure.** An edit can run for minutes with no visible
progress. `sd_wait()` backs off rather than hammering, and its timeout is a
client-side give-up: the job keeps running server-side and `sd_wait(job)`
resumes it. Jobs are deleted an hour after creation, which is the real
deadline.

## Not spending money by accident

Every client carries a budget, enforced before requests leave your machine.

```r
client <- sd_client(budget = sd_budget(max_operations = 5, max_pages = 40))

# The cheap first run: one operation, three pages, fastest model tier.
client <- sd_client(budget = sd_budget(small_sample = TRUE))
```

* `max_operations` is the hard stop. Only `sd_edit()` is billable; uploads,
  polls and exports are free.
* `max_pages` refuses an oversized document after the free upload and before
  any billable edit. The API reports chunks rather than pages, so the gate
  compares against `ceiling(chunks_count / chunks_per_page)` -- an estimate,
  default 12 chunks per page, tunable per document. It is an estimate on
  purpose and the error message says so.
* `sd_knit()` bounds its own review loop with `max_rounds`, and answers a
  large-edit continue prompt with `continue = FALSE` by default: it keeps the
  work already applied rather than spending more unasked.

## Tests, with no key and no network

The HTTP transport is a plain function on the client, so the whole suite runs
against recorded payloads:

```r
fake <- function(req) httr2::response(200L, body = charToRaw('{"status":"ok"}'))
client <- sd_client(api_key = "sk_x", transport = fake)
```

```
$ R CMD check --as-cran superdocsr_0.1.0.tar.gz
Status: OK
```

The vignette runs the same way -- every output in
`vignette("research-paper-workflow")` is real, produced offline.

The tests cover the behaviours worth doubting rather than the mocks: that a
budget refusal never reaches the network, that the double-parsed batch
populates every field, that a top-level `approved` is always sent, that
backoff genuinely lengthens the gap between polls, that a timeout is reported
as a client give-up, that a review returning nothing leaves the job open
instead of approving, and that an export writes real bytes before it claims
success.

## Known limits

* Documents over ~20 MB need the pre-signed upload path
  (`POST /v1/uploads`), which this package does not wrap yet. `sd_upload()`
  streams from disk and handles everything below that ceiling; above it the
  API returns a 413 and the error message points at the fix.
* SSE streaming is not wrapped. `sd_wait()` polls, which is the documented
  alternative and is enough for a script.
* Multi-document sessions are not modelled; one document per session.
* `max_pages` is an estimate derived from chunk count, not a rendered page
  count. Nothing client-side can know the true page count of a `.docx`
  without rendering it, and the package says estimate rather than pretending
  otherwise.

## License

MIT. See `LICENSE`.

---

Built by Aditya Meshram for the SuperDocs task.
