# Asking for an edit, and the job object that comes back.

#' Ask SuperDocs to edit a document
#'
#' Starts an AI edit against the document's session. By default the job pauses
#' before anything is written: `approval_mode = "ask_every_time"` means the AI
#' proposes changes and waits for [sd_approve()]. Auto-apply exists, but you
#' have to ask for it by name.
#'
#' This is the one billable call in the package, so it is the one that spends
#' from the client's [sd_budget()]. The spend happens before the request is
#' sent; if the budget refuses, nothing is sent and nothing is charged.
#'
#' @param document An [sd_document()] from [sd_upload()], or an [sd_job()] /
#'   session id if you are continuing earlier work.
#' @param instruction What to change, in plain language. Targeted instructions
#'   land better than sweeping ones: "tighten the discussion section" beats
#'   "improve the paper".
#' @param async `TRUE` (default) uses `POST /v1/chat/async` and returns
#'   immediately with a job to poll. `FALSE` uses the synchronous
#'   `POST /v1/chat`, which cannot pause for review and therefore requires
#'   `approval_mode = "approve_all"`.
#' @param approval_mode `"ask_every_time"` (default) proposes changes and
#'   waits. `"approve_all"` applies them as they are made -- appropriate for
#'   throwaway drafts, not for a paper you are about to submit.
#' @param model_tier One of `"core"`, `"turbo"`, `"pro"`, `"max"`, or `NULL`
#'   for the server default. `small_sample` budgets default to `"turbo"`.
#' @param thinking_depth One of `"fast"`, `"balanced"`, `"deep"`, or `NULL`.
#' @param response_mode `"compact"` keeps the full document HTML out of every
#'   poll and surfaces per-section diffs instead -- worth setting for long
#'   manuscripts. `NULL` uses the server default.
#' @param document_html Send document HTML explicitly. Only needed to load or
#'   replace the session's document; the server keeps it between turns
#'   otherwise. Send it verbatim if you send it at all -- stripping
#'   `data-chunk-id` attributes is what breaks targeted editing.
#' @param client An [sd_client()]. Taken from `document` when it has one.
#'
#' @return An object of class `sd_job`.
#' @seealso [sd_wait()] to poll it, [sd_changes()] to read what it proposes.
#' @export
#' @examples
#' \dontrun{
#' doc <- sd_upload("manuscript.docx")
#' job <- sd_edit(doc, "Tighten the abstract to 150 words without losing the result.")
#' job <- sd_wait(job)
#' sd_changes(job)
#' }
sd_edit <- function(document,
                    instruction,
                    async = TRUE,
                    approval_mode = c("ask_every_time", "approve_all"),
                    model_tier = NULL,
                    thinking_depth = NULL,
                    response_mode = NULL,
                    document_html = NULL,
                    client = NULL) {
  approval_mode <- match.arg(approval_mode)
  client <- sd_client_of(document, client)
  session_id <- sd_session_of(document)

  if (!is.character(instruction) || length(instruction) != 1L || !nzchar(trimws(instruction))) {
    stop(
      "`instruction` must be a single non-empty string.\n",
      "  Fix: say what should change, e.g. \"rewrite the limitations paragraph in the past tense\".",
      call. = FALSE
    )
  }
  if (!isTRUE(async) && identical(approval_mode, "ask_every_time")) {
    stop(
      "A synchronous edit cannot pause for review.\n",
      "  Cause: `async = FALSE` uses POST /v1/chat, which applies changes and returns.\n",
      "  Fix:   keep `async = TRUE` to review changes, or pass ",
      "`approval_mode = \"approve_all\"` to accept that the edit lands unreviewed.",
      call. = FALSE
    )
  }

  model_tier <- model_tier %||% if (client$budget$small_sample) "turbo" else NULL
  model_tier <- sd_match_or_null(model_tier, c("core", "turbo", "pro", "max"), "model_tier")
  thinking_depth <- sd_match_or_null(thinking_depth, c("fast", "balanced", "deep"), "thinking_depth")
  response_mode <- sd_match_or_null(response_mode, c("compact", "full"), "response_mode")

  body <- sd_drop_null(list(
    message = instruction,
    session_id = session_id,
    document_html = document_html,
    model_tier = model_tier,
    thinking_depth = thinking_depth,
    response_mode = response_mode,
    approval_mode = if (isTRUE(async)) approval_mode else NULL
  ))

  sd_spend(client, 1L, what = "edit")

  path <- if (isTRUE(async)) "/v1/chat/async" else "/v1/chat"
  req <- httr2::req_body_json(sd_req(client, path, method = "POST"), body)
  parsed <- sd_json(sd_perform(client, req))

  if (isTRUE(async)) {
    sd_job(
      client = client,
      job_id = parsed$job_id,
      session_id = parsed$session_id %||% session_id,
      status = parsed$status %||% "pending"
    )
  } else {
    # One return type for both paths: a synchronous turn is a job that was
    # already finished when it arrived.
    sd_job(
      client = client,
      job_id = NA_character_,
      session_id = parsed$session_id %||% session_id,
      status = "completed",
      result = parsed
    )
  }
}

#' A SuperDocs async job
#'
#' Constructor for the object [sd_edit()] returns. Build one yourself to resume
#' polling a `job_id` you persisted -- after an R session restart, for
#' instance. Jobs are deleted one hour after they are created, so a job id
#' older than that is gone rather than merely slow.
#'
#' @param client An [sd_client()].
#' @param job_id Job identifier. Opaque; treat it as a string.
#' @param session_id Session the job belongs to.
#' @param status One of `pending`, `in_progress`, `awaiting_approval`,
#'   `completed`, `failed`, `cancelled`.
#' @param progress Progress percentage reported by the API.
#' @param result Result list, present once the job completes.
#' @param error Error string, present when the job failed.
#' @param metadata Metadata list, carrying `pending_changes`, `awaiting_kind`,
#'   `continue_prompt` and `intermediate_responses`.
#' @param job_type Job type reported by the API.
#'
#' @return An object of class `sd_job`.
#' @export
#' @examples
#' client <- sd_client(api_key = "sk_x", transport = function(req) req)
#' sd_job(client, job_id = "550e8400", session_id = "paper-2026")
sd_job <- function(client,
                   job_id,
                   session_id,
                   status = "pending",
                   progress = NA_real_,
                   result = NULL,
                   error = NULL,
                   metadata = NULL,
                   job_type = NA_character_) {
  sd_stopifnot_client(client)
  structure(
    list(
      client = client,
      job_id = if (is.null(job_id)) NA_character_ else as.character(job_id),
      session_id = sd_check_session_id(session_id),
      status = status,
      progress = progress,
      result = result,
      error = error,
      metadata = metadata,
      job_type = job_type
    ),
    class = "sd_job"
  )
}

#' @export
print.sd_job <- function(x, ...) {
  cat("<sd_job>\n")
  cat("  job:      ", x$job_id, "\n", sep = "")
  cat("  session:  ", x$session_id, "\n", sep = "")
  cat("  status:   ", x$status, sep = "")
  kind <- sd_awaiting_kind(x)
  if (!is.na(kind)) {
    cat(" (", kind, ")", sep = "")
  }
  cat("\n")
  if (!is.na(x$progress)) {
    cat("  progress: ", x$progress, "%\n", sep = "")
  }
  if (!is.null(x$error)) {
    cat("  error:    ", sd_flatten_detail(x$error), "\n", sep = "")
  }
  n <- length(sd_raw_pending_changes(x))
  if (n > 0L) {
    cat("  proposed: ", n, " change(s) -- inspect with sd_changes()\n", sep = "")
  }
  invisible(x)
}

#' What a paused job is waiting for
#'
#' `awaiting_approval` covers two different pauses. A change review wants
#' [sd_approve()]; a large-edit continue prompt wants [sd_continue()]. Sending
#' the wrong one is rejected with a 409, so branch on this first.
#'
#' @param job An [sd_job()].
#' @return `"continue_prompt"`, `"change_review"`, or `NA` when the job is not
#'   paused.
#' @export
#' @examples
#' client <- sd_client(api_key = "sk_x", transport = function(req) req)
#' job <- sd_job(client, "j1", "paper-2026", status = "in_progress")
#' sd_awaiting_kind(job)
sd_awaiting_kind <- function(job) {
  if (!identical(job$status, "awaiting_approval")) {
    return(NA_character_)
  }
  kind <- job$metadata$awaiting_kind
  if (identical(kind, "continue_prompt")) "continue_prompt" else "change_review"
}

# ---- internals --------------------------------------------------------------

sd_drop_null <- function(x) x[!vapply(x, is.null, logical(1))]

sd_match_or_null <- function(value, choices, arg) {
  if (is.null(value)) {
    return(NULL)
  }
  if (!is.character(value) || length(value) != 1L || !value %in% choices) {
    stop("`", arg, "` must be one of ", paste0("\"", choices, "\"", collapse = ", "),
      ", or NULL.",
      call. = FALSE
    )
  }
  value
}
