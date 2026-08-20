# superdocsr 0.1.0

First release.

* `sd_client()` builds an authenticated SuperDocs client. The HTTP transport is
  a plain function stored on the client, so tests and vignettes can swap in a
  fake one and run with no network and no API key.
* `sd_upload()` loads a `.docx`/`.pdf`/`.html`/`.md`/`.txt`/`.rtf` file as the
  active document of a session, streaming the file from disk rather than
  holding it in memory.
* `sd_edit()` starts a review-gated AI edit. `approval_mode` defaults to
  `"ask_every_time"`; auto-apply has to be asked for by name.
* `sd_wait()` polls `GET /v1/jobs/{job_id}` with exponential backoff and a
  wall-clock timeout, and stops on every terminal or paused state instead of
  spinning.
* `sd_changes()` returns the proposed changes as a data frame. Batches that
  arrive as a JSON-encoded string in `content` are parsed a second time with
  `jsonlite::fromJSON()`, which is what keeps every field from reading as `NA`.
* `sd_approve()` approves or denies changes by id, always sending the
  top-level `approved` field the endpoint requires.
* `sd_continue()` answers the large-edit continue prompt, so a paused job is
  resumed or stopped deliberately rather than waited out.
* `sd_export()` writes the approved document to disk as `docx`, `pdf`, `html`,
  `markdown`, or `txt`, and surfaces the `X-Export-Warnings` header.
* `sd_knit()` renders an `.Rmd` with `rmarkdown::render()` and runs the same
  upload, edit, review, export workflow over the result.
* `sd_budget()` caps billable operations per client and refuses documents above
  an estimated page count, so a loop cannot quietly drain a quota.
