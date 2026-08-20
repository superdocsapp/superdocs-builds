# Polling a job to a stopping point.

#' Wait for a job to reach a stopping point
#'
#' Polls `GET /v1/jobs/{job_id}` until the job stops needing to be polled, and
#' returns it. Four things count as a stopping point: `completed`, `failed`,
#' `cancelled`, and `awaiting_approval` -- the last one being the review gate,
#' which is a result, not a delay.
#'
#' An edit on a real paper takes anywhere from ten seconds to several minutes
#' with nothing visible happening in between. That is the API working, not a
#' crash. The default `timeout` of 300 seconds suits a multi-section edit; a
#' full-document restructure of a long manuscript wants more. The server caps
#' any single turn at 30 minutes, and jobs are deleted an hour after creation,
#' so there is no point waiting longer than that.
#'
#' @param job An [sd_job()].
#' @param timeout Wall-clock seconds to wait before giving up.
#' @param backoff If `TRUE` (default), the gap between polls grows by half each
#'   time, up to `max_interval`. If `FALSE`, poll every `interval` seconds.
#' @param interval First gap between polls, in seconds.
#' @param max_interval Longest gap between polls, in seconds.
#' @param verbose Report progress while waiting. Defaults to on in an
#'   interactive session, off in a script.
#'
#' @return The updated [sd_job()]. Raises `sd_job_failed` if the job failed or
#'   was cancelled, and `sd_timeout_error` if `timeout` runs out first -- the
#'   job id stays valid in that case, so you can call `sd_wait()` again.
#' @export
#' @examples
#' \dontrun{
#' job <- sd_wait(sd_edit(doc, "Rewrite the conclusion."), timeout = 600)
#' sd_awaiting_kind(job)
#' }
sd_wait <- function(job,
                    timeout = 300,
                    backoff = TRUE,
                    interval = 2,
                    max_interval = 30,
                    verbose = interactive()) {
  if (!inherits(job, "sd_job")) {
    stop("`job` must come from sd_edit() or sd_job().", call. = FALSE)
  }
  if (!is.numeric(timeout) || length(timeout) != 1L || timeout <= 0) {
    stop("`timeout` must be a single positive number of seconds.", call. = FALSE)
  }

  started <- Sys.time()
  wait <- interval
  announced <- 0

  repeat {
    if (sd_is_settled(job)) {
      return(sd_stop_if_failed(job))
    }
    if (is.na(job$job_id)) {
      stop(
        "This job has no job_id, so there is nothing to poll.\n",
        "  Cause: it came from a synchronous sd_edit(async = FALSE) call.\n",
        "  Fix:   read its result directly; it finished before it was returned.",
        call. = FALSE
      )
    }

    elapsed <- as.numeric(difftime(Sys.time(), started, units = "secs"))
    if (elapsed > timeout) {
      stop(
        structure(
          class = c("sd_timeout_error", "error", "condition"),
          list(
            message = paste0(
              "Job ", job$job_id, " was still '", job$status, "' after ",
              round(elapsed), "s (timeout ", timeout, "s).\n",
              "  Note: this is a client-side give-up, not a server failure. The job ",
              "keeps running.\n",
              "  Fix:  call sd_wait(job, timeout = ", max(600, timeout * 2),
              ") to keep waiting, or split the instruction into smaller edits. ",
              "Jobs are deleted one hour after they are created."
            ),
            call = NULL,
            job = job
          )
        )
      )
    }

    if (isTRUE(verbose) && elapsed - announced >= 30) {
      message("  still ", job$status, "... (", round(elapsed), "s elapsed)")
      announced <- elapsed
    }

    Sys.sleep(min(wait, max(0, timeout - elapsed)))
    if (isTRUE(backoff)) {
      wait <- min(wait * 1.5, max_interval)
    }
    job <- sd_job_refresh(job)
  }
}

#' Answer a large-edit continue prompt
#'
#' A very large edit applies what it can, keeps that work, and pauses to ask
#' whether to carry on. That pause reports `status = "awaiting_approval"` with
#' [sd_awaiting_kind()] of `"continue_prompt"`, and it is answered here rather
#' than with [sd_approve()] -- sending an approval to a continue prompt is
#' rejected with a 409.
#'
#' Continuing costs more operations, which is exactly why this is a call you
#' make rather than something [sd_wait()] does for you.
#'
#' @param job An [sd_job()] paused on a continue prompt.
#' @param proceed `TRUE` to finish the rest of the edit, `FALSE` to stop and
#'   keep everything applied so far.
#'
#' @return The refreshed [sd_job()].
#' @export
#' @examples
#' \dontrun{
#' if (identical(sd_awaiting_kind(job), "continue_prompt")) {
#'   message(job$metadata$continue_prompt$message)
#'   job <- sd_continue(job, proceed = TRUE)
#' }
#' }
sd_continue <- function(job, proceed = TRUE) {
  if (!inherits(job, "sd_job")) {
    stop("`job` must come from sd_edit() or sd_job().", call. = FALSE)
  }
  if (!identical(sd_awaiting_kind(job), "continue_prompt")) {
    stop(
      "This job is not paused on a continue prompt (status '", job$status, "').\n",
      "  Fix: branch on sd_awaiting_kind(job); a 'change_review' pause is answered ",
      "with sd_approve().",
      call. = FALSE
    )
  }

  body <- list(job_id = job$job_id, `continue` = isTRUE(proceed))
  req <- httr2::req_body_json(
    sd_req(job$client, paste0("/v1/chat/", job$session_id, "/continue"), method = "POST"),
    body
  )
  sd_perform(job$client, req)
  sd_job_refresh(job)
}

#' Cancel a running job
#'
#' Stops the AI mid-edit. Changes already applied stay in the document; pending
#' ones are discarded. Only `pending` and `in_progress` jobs can be cancelled.
#'
#' @param job An [sd_job()].
#' @return The refreshed [sd_job()].
#' @export
#' @examples
#' \dontrun{
#' sd_cancel(job)
#' }
sd_cancel <- function(job) {
  if (!inherits(job, "sd_job")) {
    stop("`job` must come from sd_edit() or sd_job().", call. = FALSE)
  }
  req <- sd_req(job$client, paste0("/v1/jobs/", job$job_id, "/cancel"), method = "POST")
  sd_perform(job$client, req)
  sd_job_refresh(job)
}

# ---- internals --------------------------------------------------------------

SD_SETTLED <- c("completed", "failed", "cancelled", "awaiting_approval")

sd_is_settled <- function(job) job$status %in% SD_SETTLED

sd_stop_if_failed <- function(job) {
  if (job$status %in% c("failed", "cancelled")) {
    stop(
      structure(
        class = c("sd_job_failed", "error", "condition"),
        list(
          message = paste0(
            "Job ", job$job_id, " ", job$status, ".\n",
            "  Cause: ", if (is.null(job$error)) "the API reported no error text" else sd_flatten_detail(job$error), "\n",
            "  Fix:   nothing was approved, so the document is untouched. Re-run the ",
            "edit, or split the instruction if it timed out server-side."
          ),
          call = NULL,
          job = job
        )
      )
    )
  }
  job
}

sd_job_refresh <- function(job) {
  parsed <- sd_json(sd_perform(
    job$client,
    sd_req(job$client, paste0("/v1/jobs/", job$job_id))
  ))
  job$status <- parsed$status %||% job$status
  job$progress <- if (is.null(parsed$progress)) NA_real_ else as.numeric(parsed$progress)
  job$result <- parsed$result
  job$error <- parsed$error
  job$metadata <- parsed$metadata
  job$job_type <- parsed$job_type %||% job$job_type
  job
}
