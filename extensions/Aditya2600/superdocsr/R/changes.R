# Reading what the AI proposes -- including the second JSON parse that makes
# the fields readable instead of empty.

#' Read the changes a job proposes
#'
#' Returns one row per proposed change, so you can look at what the AI wants to
#' do before any of it touches the document.
#'
#' @section The second parse:
#' Proposed changes reach a client by two routes, and they are not shaped the
#' same. `metadata$pending_changes` arrives as ordinary JSON objects. The
#' batched form, in `metadata$intermediate_responses`, arrives with its payload
#' in a `content` field that is *itself a JSON-encoded string* -- the same
#' double encoding the SSE `proposed_change_batch` event uses. Parsing the
#' response once leaves `content` as a character scalar, and every field read
#' off it comes back `NULL`. This function calls [jsonlite::fromJSON()] a
#' second time on that string, which is the difference between a populated
#' table and a table of `NA`s. It is the single most common thing integrators
#' miss, so it is handled here rather than left to the caller.
#'
#' Both routes are read and merged, deduplicated by `change_id`. Changes
#' already decided before a reconnect (reported in
#' `metadata$pending_batch_decisions`) are marked in the `decided` column so a
#' review UI can skip them.
#'
#' @param job An [sd_job()].
#' @param refresh Re-poll the job first. `TRUE` by default, so the table is
#'   never stale.
#'
#' @return A data frame of class `sd_changes`, one row per proposed change,
#'   with columns `change_id`, `operation` (`edit`, `create` or `delete`),
#'   `chunk_id`, `document_id`, `ai_explanation`, `old_html`, `new_html`,
#'   `insert_after_chunk_id`, `batch_id`, `batch_total` and `decided`. Zero
#'   rows means the AI proposed nothing -- an honest answer, not a failure.
#' @seealso [sd_approve()] to act on the result.
#' @export
#' @examples
#' \dontrun{
#' changes <- sd_changes(job)
#' changes[, c("change_id", "operation", "ai_explanation")]
#' sd_approve(job, changes$change_id[changes$operation != "delete"])
#' }
sd_changes <- function(job, refresh = TRUE) {
  if (!inherits(job, "sd_job")) {
    stop("`job` must come from sd_edit() or sd_job().", call. = FALSE)
  }
  if (isTRUE(refresh) && !is.na(job$job_id)) {
    job <- sd_job_refresh(job)
  }

  raw <- sd_raw_pending_changes(job)
  decided <- names(job$metadata$pending_batch_decisions %||% list())

  df <- data.frame(
    change_id = sd_field(raw, "change_id"),
    operation = sd_field(raw, "operation"),
    chunk_id = sd_field(raw, "chunk_id"),
    document_id = sd_field(raw, "document_id"),
    ai_explanation = sd_field(raw, "ai_explanation"),
    old_html = sd_field(raw, "old_html"),
    new_html = sd_field(raw, "new_html"),
    insert_after_chunk_id = sd_field(raw, "insert_after_chunk_id"),
    batch_id = sd_field(raw, "batch_id"),
    batch_total = sd_field(raw, "batch_total", as = as.integer),
    stringsAsFactors = FALSE
  )
  df$decided <- df$change_id %in% decided

  attr(df, "job") <- job
  class(df) <- c("sd_changes", "data.frame")
  df
}

SD_CHANGE_COLS <- c(
  "change_id", "operation", "chunk_id", "document_id", "ai_explanation",
  "old_html", "new_html", "insert_after_chunk_id", "batch_id",
  "batch_total", "decided"
)

# Filtering rows keeps the review printout; selecting columns gives back a
# plain data frame, because a two-column slice is a table, not a review.
#' @export
`[.sd_changes` <- function(x, ...) {
  job <- attr(x, "job")
  out <- NextMethod()
  if (!is.data.frame(out)) {
    return(out)
  }
  if (all(SD_CHANGE_COLS %in% names(out))) {
    class(out) <- c("sd_changes", "data.frame")
    attr(out, "job") <- job
  } else {
    class(out) <- "data.frame"
    attr(out, "job") <- NULL
  }
  out
}

#' @export
print.sd_changes <- function(x, ..., max_rows = 20L, width = 60L) {
  job <- attr(x, "job")
  if (!all(SD_CHANGE_COLS %in% names(x))) {
    return(print.data.frame(x, ...))
  }
  if (nrow(x) == 0L) {
    cat("<sd_changes> no changes proposed\n")
    if (!is.null(job) && identical(sd_awaiting_kind(job), "continue_prompt")) {
      cat("  The job is paused on a continue prompt, not a review.\n")
      cat("  ", job$metadata$continue_prompt$message %||% "", "\n", sep = "")
      cat("  Answer it with sd_continue(job, proceed = TRUE/FALSE).\n")
    }
    return(invisible(x))
  }

  cat("<sd_changes> ", nrow(x), " proposed change(s)",
    if (!is.null(job)) paste0(" on session ", job$session_id) else "", "\n",
    sep = ""
  )
  shown <- min(nrow(x), max_rows)
  for (i in seq_len(shown)) {
    cat("\n", i, ". [", x$operation[i], "] ", x$change_id[i],
      if (isTRUE(x$decided[i])) "  (already decided)" else "", "\n",
      sep = ""
    )
    if (!is.na(x$ai_explanation[i])) {
      cat("   why: ", x$ai_explanation[i], "\n", sep = "")
    }
    if (!is.na(x$old_html[i])) {
      cat("   -   ", sd_text_preview(x$old_html[i], width), "\n", sep = "")
    }
    if (!is.na(x$new_html[i])) {
      cat("   +   ", sd_text_preview(x$new_html[i], width), "\n", sep = "")
    }
  }
  if (nrow(x) > shown) {
    cat("\n... ", nrow(x) - shown, " more. Print with max_rows = Inf.\n", sep = "")
  }
  cat("\nNothing is applied until sd_approve() names the ids you accept.\n")
  invisible(x)
}

# ---- internals --------------------------------------------------------------

# Collect proposed changes from both places a polled job carries them.
sd_raw_pending_changes <- function(job) {
  meta <- job$metadata
  if (is.null(meta)) {
    return(list())
  }

  out <- sd_as_change_list(meta$pending_changes)

  for (event in meta$intermediate_responses %||% list()) {
    if (!identical(event$type, "proposed_change_batch")) {
      next
    }
    batch <- sd_parse_content(event$content)
    changes <- sd_as_change_list(batch$changes)
    # The batch id and total live on the envelope, not on each change.
    changes <- lapply(changes, function(change) {
      change$batch_id <- change$batch_id %||% batch$batch_id
      change$batch_total <- change$batch_total %||% batch$batch_total
      change
    })
    out <- c(out, changes)
  }

  ids <- vapply(out, function(change) as.character(change$change_id %||% NA_character_), character(1))
  out[!duplicated(ids) | is.na(ids)]
}

# The second jsonlite::fromJSON() call. `content` is a JSON-encoded string
# nested inside JSON that was already parsed once; without this the payload
# stays a character scalar and every field below it reads as NULL.
sd_parse_content <- function(content) {
  if (is.null(content)) {
    return(list())
  }
  if (is.character(content) && length(content) == 1L) {
    parsed <- tryCatch(
      jsonlite::fromJSON(content, simplifyVector = FALSE),
      error = function(e) NULL
    )
    if (is.null(parsed)) {
      warning(
        "A proposed_change_batch carried a `content` field that is not valid JSON; ",
        "skipping that batch.",
        call. = FALSE
      )
      return(list())
    }
    return(parsed)
  }
  if (is.list(content)) {
    return(content)
  }
  list()
}

# Accept a list of changes, a single change, or either of those still wrapped
# in a JSON string.
sd_as_change_list <- function(x) {
  if (is.null(x)) {
    return(list())
  }
  if (is.character(x) && length(x) == 1L) {
    return(sd_as_change_list(sd_parse_content(x)))
  }
  if (!is.list(x)) {
    return(list())
  }
  if (!is.null(x$change_id) || !is.null(x$operation)) {
    return(list(x))
  }
  if (!is.null(x$changes)) {
    return(sd_as_change_list(x$changes))
  }
  Filter(is.list, unname(x))
}

sd_field <- function(records, name, as = as.character) {
  if (length(records) == 0L) {
    return(as(character(0)))
  }
  vapply(
    records,
    function(record) {
      value <- record[[name]]
      if (is.null(value) || length(value) == 0L) as(NA) else as(value[[1]])
    },
    as(NA)
  )
}

sd_text_preview <- function(html, width = 60L) {
  if (is.na(html)) {
    return("")
  }
  text <- gsub("<[^>]*>", " ", html)
  text <- trimws(gsub("[[:space:]]+", " ", text))
  if (nchar(text) > width) paste0(substr(text, 1, width - 3), "...") else text
}
