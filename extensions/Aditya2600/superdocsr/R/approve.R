# The gate. Nothing in this package writes to a document except through here.

#' Approve or deny proposed changes
#'
#' Sends a decision for the change ids you name to
#' `POST /v1/chat/{session_id}/approve`. Approved changes are applied
#' atomically; denied ones are discarded, and any `feedback` goes back to the
#' AI, which may then propose a revision. After the call the job resumes, so
#' poll it again with [sd_wait()] -- a review can go several rounds.
#'
#' `change_ids` has no default on purpose. There is no "approve everything"
#' switch in this package, because an unreviewed AI edit to a paper you are
#' about to submit is exactly the failure this workflow exists to prevent. To
#' accept a whole batch, say so explicitly:
#' `sd_approve(job, sd_changes(job)$change_id)`.
#'
#' @param job An [sd_job()] paused on a change review. Check with
#'   [sd_awaiting_kind()] first; a continue prompt is answered by
#'   [sd_continue()] and rejects an approval with a 409.
#' @param change_ids Character vector of `change_id` values from [sd_changes()].
#' @param approved `TRUE` to apply them, `FALSE` to discard them.
#' @param feedback Optional note to the AI, most useful alongside
#'   `approved = FALSE`: say what to do instead and the next proposal reflects
#'   it.
#'
#' @return The refreshed [sd_job()], invisibly.
#' @seealso [sd_deny()] for the denying half.
#' @export
#' @examples
#' \dontrun{
#' changes <- sd_changes(job)
#' keep <- changes$change_id[changes$operation == "edit"]
#' job <- sd_approve(job, keep)
#' job <- sd_wait(job)
#' }
sd_approve <- function(job, change_ids, approved = TRUE, feedback = NULL) {
  if (!inherits(job, "sd_job")) {
    stop("`job` must come from sd_edit() or sd_job().", call. = FALSE)
  }
  if (missing(change_ids)) {
    stop(
      "Name the changes you are deciding on.\n",
      "  Cause: superdocsr has no approve-everything default; an unreviewed edit ",
      "is the thing this workflow exists to prevent.\n",
      "  Fix:   sd_approve(job, sd_changes(job)$change_id) to accept the whole batch, ",
      "or pass the subset you agree with.",
      call. = FALSE
    )
  }
  change_ids <- unique(as.character(change_ids))
  change_ids <- change_ids[!is.na(change_ids) & nzchar(change_ids)]
  if (length(change_ids) == 0L) {
    stop("`change_ids` is empty; there is nothing to decide.", call. = FALSE)
  }
  if (!is.logical(approved) || length(approved) != 1L || is.na(approved)) {
    stop("`approved` must be TRUE or FALSE.", call. = FALSE)
  }
  if (is.na(job$job_id)) {
    stop(
      "This job has no job_id, so there is nothing to approve.\n",
      "  Cause: a synchronous sd_edit(async = FALSE) turn applies its changes and returns; ",
      "there is no review stage to gate.\n",
      "  Fix:   use async = TRUE with approval_mode = \"ask_every_time\" to review edits.",
      call. = FALSE
    )
  }
  if (identical(sd_awaiting_kind(job), "continue_prompt")) {
    stop(
      "This job is paused on a continue prompt, not a change review.\n",
      "  Fix: answer it with sd_continue(job, proceed = TRUE/FALSE). ",
      "Approving a continue prompt is rejected with a 409.",
      call. = FALSE
    )
  }

  # `approved` is required at the top level even when every entry in `changes`
  # carries its own. Omitting it is a documented 422.
  body <- sd_drop_null(list(
    job_id = job$job_id,
    approved = approved,
    feedback = feedback,
    changes = lapply(change_ids, function(id) list(change_id = id, approved = approved))
  ))

  req <- httr2::req_body_json(
    sd_req(job$client, paste0("/v1/chat/", job$session_id, "/approve"), method = "POST"),
    body,
    auto_unbox = TRUE
  )
  sd_perform(job$client, req)
  invisible(sd_job_refresh(job))
}

#' Deny proposed changes
#'
#' Shorthand for `sd_approve(approved = FALSE)`. Denying with feedback is the
#' useful shape: the AI reads it and may propose a revision, so keep polling.
#'
#' @inheritParams sd_approve
#' @return The refreshed [sd_job()], invisibly.
#' @export
#' @examples
#' \dontrun{
#' job <- sd_deny(job, "ch_3", feedback = "Keep the hedge; the effect is not significant.")
#' }
sd_deny <- function(job, change_ids, feedback = NULL) {
  sd_approve(job, change_ids, approved = FALSE, feedback = feedback)
}
