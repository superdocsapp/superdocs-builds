# The knitr entry point: render a paper, then run the whole workflow over it.

#' Render an R Markdown paper and edit it through SuperDocs
#'
#' Calls [rmarkdown::render()] on `input_rmd`, uploads the rendered file, asks
#' for `instruction`, waits for the proposal, hands it to `review`, applies
#' exactly the decisions `review` returns, and optionally exports the result.
#'
#' The review step is a function you supply, and there is no default that
#' approves anything. `sd_review_console()`, the default, asks a human in an
#' interactive session and refuses to guess in a script. Every change gets an
#' explicit decision -- ids you name are approved, the rest are denied -- so
#' the job never sits blocking the session waiting on a review nobody is going
#' to give.
#'
#' @section Stopping rules:
#' Two loops live here, and both are bounded. `max_rounds` caps how many times
#' a denied-with-feedback round trip may repeat, because the AI is entitled to
#' keep proposing revisions and each one costs. `continue` decides what happens
#' when a large edit pauses to ask whether to keep going; it defaults to
#' `FALSE`, which keeps the work already applied and stops, rather than
#' spending more without being asked. On top of both, the client's
#' [sd_budget()] is the hard ceiling.
#'
#' @param input_rmd Path to the `.Rmd` file.
#' @param instruction What to change, in plain language.
#' @param output_format Passed to [rmarkdown::render()]. `"word_document"` by
#'   default, which gives SuperDocs the `.docx` it round-trips with the highest
#'   fidelity.
#' @param client An [sd_client()].
#' @param review Function taking the [sd_changes()] data frame and returning
#'   the `change_id` values to approve. Return `character(0)` to deny
#'   everything, or `NULL` to stop and leave the review open for a human.
#' @param export_path Where to write the approved document. `NULL` skips the
#'   export; nothing is exported when nothing was approved.
#' @param export_format Format for the export. Inferred from `export_path`'s
#'   extension when possible, otherwise `"docx"`.
#' @param timeout Seconds to wait on each poll, passed to [sd_wait()].
#' @param max_rounds Maximum review rounds before giving up and leaving the job
#'   for a human.
#' @param continue Answer given to a large-edit continue prompt: `FALSE`
#'   (default) stops and keeps what is applied, `TRUE` finishes the edit.
#' @param render_args Extra arguments for [rmarkdown::render()].
#' @param ... Passed to [sd_edit()], e.g. `model_tier = "max"`.
#'
#' @return An object of class `sd_knit_result`: a list with `rendered`,
#'   `document`, `job`, `changes`, `approved`, `denied` and `export_path`.
#' @export
#' @examples
#' \dontrun{
#' result <- sd_knit(
#'   "paper.Rmd",
#'   "Tighten the discussion section; keep every citation exactly as written.",
#'   export_path = "paper-revised.docx"
#' )
#' result$changes
#' }
sd_knit <- function(input_rmd,
                    instruction,
                    output_format = "word_document",
                    client = sd_client(),
                    review = sd_review_console,
                    export_path = NULL,
                    export_format = NULL,
                    timeout = 300,
                    max_rounds = 3L,
                    continue = FALSE,
                    render_args = list(),
                    ...) {
  if (!requireNamespace("rmarkdown", quietly = TRUE)) {
    stop(
      "sd_knit() needs the rmarkdown package.\n  Fix: install.packages(\"rmarkdown\").",
      call. = FALSE
    )
  }
  if (!file.exists(input_rmd)) {
    stop("No file at '", input_rmd, "'.", call. = FALSE)
  }
  if (!is.function(review)) {
    stop("`review` must be a function of one argument (the sd_changes table).", call. = FALSE)
  }

  rendered <- do.call(
    rmarkdown::render,
    c(
      list(input = input_rmd, output_format = output_format, quiet = TRUE, envir = new.env()),
      render_args
    )
  )

  document <- sd_upload(rendered, client)
  job <- sd_wait(sd_edit(document, instruction, client = client, ...), timeout = timeout)

  approved <- character(0)
  denied <- character(0)
  changes <- sd_changes(job, refresh = FALSE)

  for (round in seq_len(max_rounds)) {
    if (!identical(job$status, "awaiting_approval")) {
      break
    }

    if (identical(sd_awaiting_kind(job), "continue_prompt")) {
      prompt <- job$metadata$continue_prompt
      message(
        "Large edit paused: ", prompt$message %||% "the edit did not finish in one turn.",
        "\n  Answering continue = ", continue, "."
      )
      job <- sd_wait(sd_continue(job, proceed = continue), timeout = timeout)
      next
    }

    changes <- sd_changes(job, refresh = FALSE)
    if (nrow(changes) == 0L) {
      break
    }

    decision <- review(changes)
    if (is.null(decision)) {
      message(
        "Review left open after round ", round,
        ". The job stays in awaiting_approval; decide with sd_approve() / sd_deny()."
      )
      break
    }

    yes <- intersect(as.character(decision), changes$change_id)
    no <- setdiff(changes$change_id, yes)

    if (length(yes)) {
      job <- sd_approve(job, yes)
      approved <- c(approved, yes)
    }
    if (length(no)) {
      job <- sd_deny(job, no)
      denied <- c(denied, no)
    }
    job <- sd_wait(job, timeout = timeout)
  }

  if (identical(job$status, "awaiting_approval") && length(approved) + length(denied) > 0L) {
    message(
      "Still awaiting approval after ", max_rounds,
      " round(s). Left for you rather than looping further."
    )
  }

  written <- NULL
  if (!is.null(export_path)) {
    if (length(approved) == 0L) {
      message("Nothing was approved, so nothing was exported.")
    } else {
      export_format <- export_format %||% sd_format_from_path(export_path)
      written <- sd_export(document, format = export_format, path = export_path)
    }
  }

  structure(
    list(
      rendered = rendered,
      document = document,
      job = job,
      changes = changes,
      approved = approved,
      denied = denied,
      export_path = written
    ),
    class = "sd_knit_result"
  )
}

#' @export
print.sd_knit_result <- function(x, ...) {
  cat("<sd_knit_result>\n")
  cat("  rendered: ", x$rendered, "\n", sep = "")
  cat("  session:  ", x$document$session_id, "\n", sep = "")
  cat("  status:   ", x$job$status, "\n", sep = "")
  cat("  proposed: ", nrow(x$changes), "\n", sep = "")
  cat("  approved: ", length(x$approved), "\n", sep = "")
  cat("  denied:   ", length(x$denied), "\n", sep = "")
  if (is.null(x$export_path)) {
    cat("  export:   none\n")
  } else {
    cat("  export:   ", x$export_path, "\n", sep = "")
  }
  if (identical(x$job$status, "awaiting_approval")) {
    cat("\n  Review still open. Next: sd_changes(result$job), then sd_approve()/sd_deny().\n")
  }
  invisible(x)
}

#' Review helpers for sd_knit()
#'
#' `sd_review_console()` prints each proposed change and asks a human which to
#' approve. In a non-interactive session it refuses to decide and raises an
#' error, because the alternative -- guessing -- is the behaviour this package
#' exists to avoid.
#'
#' `sd_review_none()` returns `NULL`, which runs the workflow up to the review
#' and stops there, leaving the job open for a person. It is the right choice
#' for a scheduled script that should prepare work rather than commit it.
#'
#' @param changes The [sd_changes()] data frame.
#' @return A character vector of `change_id` values to approve,
#'   `character(0)` to deny everything, or `NULL` to leave the review open.
#' @export
#' @examples
#' client <- sd_client(api_key = "sk_x", transport = function(req) req)
#' job <- sd_job(client, "j1", "paper-2026")
#' sd_review_none(sd_changes(job, refresh = FALSE))
sd_review_console <- function(changes) {
  if (!interactive()) {
    stop(
      "sd_review_console() will not approve changes in a non-interactive session.\n",
      "  Fix: pass review = sd_review_none to stop at the review, or supply your own ",
      "function, e.g. review = function(ch) ch$change_id[ch$operation == \"edit\"].",
      call. = FALSE
    )
  }
  print(changes)
  cat("\nEnter the numbers to approve (e.g. 1 3), 'all', or blank to deny all: ")
  answer <- trimws(readline())
  if (!nzchar(answer)) {
    return(character(0))
  }
  if (identical(tolower(answer), "all")) {
    return(changes$change_id)
  }
  picks <- suppressWarnings(as.integer(strsplit(answer, "[^0-9]+")[[1]]))
  picks <- picks[!is.na(picks) & picks >= 1L & picks <= nrow(changes)]
  changes$change_id[picks]
}

#' @rdname sd_review_console
#' @export
sd_review_none <- function(changes) NULL

# ---- internals --------------------------------------------------------------

sd_format_from_path <- function(path) {
  ext <- tolower(tools::file_ext(path))
  hit <- names(SD_EXPORT_EXT)[match(ext, SD_EXPORT_EXT)]
  if (is.na(hit)) "docx" else hit
}
