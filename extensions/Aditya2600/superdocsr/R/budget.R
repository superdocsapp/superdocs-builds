# Spending controls. Everything that can cost money or spin in a loop passes
# through here first.

#' Cap what a client may spend
#'
#' A SuperDocs operation is billable; uploads, exports and job polls are not.
#' An edit loop that goes wrong is therefore the only thing that can quietly
#' drain a quota, and this is the object that stops it.
#'
#' Three controls, all enforced before a request leaves your machine:
#'
#' * `max_operations` -- the hard stop. Each [sd_edit()] spends one operation
#'   from the client's allowance. When the allowance reaches zero the next edit
#'   raises an error instead of sending the request.
#' * `max_pages` -- the size gate. A document above this estimated page count
#'   is refused before any edit runs. Uploads are free, so this check costs
#'   nothing and happens right after the upload, in [sd_upload()].
#' * `small_sample` -- the cheap preset for a first run: one operation, three
#'   pages, and the fastest model tier.
#'
#' @section How pages are estimated:
#' The API reports `chunks_count` -- the number of addressable blocks
#' (paragraphs, headings, table rows and cells) it parsed out of the file. It
#' does not report a page count, and page count is not knowable from a `.docx`
#' without rendering it. `max_pages` therefore compares against
#' `ceiling(chunks_count / chunks_per_page)`, an estimate. The default of 12
#' chunks per page suits a double-spaced manuscript; a dense two-column paper
#' runs higher. Tune `chunks_per_page`, or set `max_pages = NULL` to switch the
#' gate off and rely on `max_operations` alone.
#'
#' @param max_operations Maximum billable operations this client may spend.
#'   `Inf` removes the cap.
#' @param max_pages Maximum estimated pages a document may have before an edit
#'   is allowed. `NULL` disables the gate.
#' @param chunks_per_page Chunks-per-page divisor used for the estimate above.
#' @param small_sample If `TRUE`, apply the cheap preset: at most one
#'   operation, at most `small_sample_pages` pages, and `model_tier = "turbo"`
#'   unless [sd_edit()] is told otherwise.
#' @param small_sample_pages Page cap used when `small_sample = TRUE`.
#'
#' @return An object of class `sd_budget`.
#' @export
#' @examples
#' sd_budget()
#' sd_budget(small_sample = TRUE)
#' sd_budget(max_operations = 3, max_pages = 40)
sd_budget <- function(max_operations = 25,
                      max_pages = NULL,
                      chunks_per_page = 12,
                      small_sample = FALSE,
                      small_sample_pages = 3) {
  if (!is.numeric(max_operations) || length(max_operations) != 1L || max_operations < 0) {
    stop("`max_operations` must be a single non-negative number.", call. = FALSE)
  }
  if (!is.null(max_pages) && (!is.numeric(max_pages) || length(max_pages) != 1L || max_pages < 1)) {
    stop("`max_pages` must be NULL or a single number >= 1.", call. = FALSE)
  }
  if (!is.numeric(chunks_per_page) || length(chunks_per_page) != 1L || chunks_per_page < 1) {
    stop("`chunks_per_page` must be a single number >= 1.", call. = FALSE)
  }

  if (isTRUE(small_sample)) {
    max_operations <- min(max_operations, 1)
    max_pages <- min(max_pages %||% small_sample_pages, small_sample_pages)
  }

  state <- new.env(parent = emptyenv())
  state$used <- 0L

  structure(
    list(
      max_operations = max_operations,
      max_pages = max_pages,
      chunks_per_page = chunks_per_page,
      small_sample = isTRUE(small_sample),
      state = state
    ),
    class = "sd_budget"
  )
}

#' @export
print.sd_budget <- function(x, ...) {
  cat("  budget:    ", x$state$used, " of ",
    if (is.finite(x$max_operations)) x$max_operations else "unlimited",
    " operations used",
    if (x$small_sample) " (small sample)" else "",
    "\n",
    sep = ""
  )
  if (!is.null(x$max_pages)) {
    cat("             max ", x$max_pages, " estimated pages per document\n", sep = "")
  }
  invisible(x)
}

#' Operations spent and left on a client
#'
#' @param client An [sd_client()].
#' @return A single number: operations spent so far, or operations still
#'   available (possibly `Inf`).
#' @export
#' @examples
#' client <- sd_client(api_key = "sk_x", transport = function(req) req)
#' sd_ops_used(client)
#' sd_ops_remaining(client)
sd_ops_used <- function(client) {
  sd_stopifnot_client(client)
  client$budget$state$used
}

#' @rdname sd_ops_used
#' @export
sd_ops_remaining <- function(client) {
  sd_stopifnot_client(client)
  client$budget$max_operations - client$budget$state$used
}

# Spend n operations or refuse. Called before the request, so a refusal costs
# nothing at all.
sd_spend <- function(client, n = 1L, what = "edit") {
  budget <- client$budget
  if (budget$state$used + n > budget$max_operations) {
    stop(
      structure(
        class = c("sd_budget_error", "error", "condition"),
        list(
          message = paste0(
            "Operation budget exhausted: this client has spent ",
            budget$state$used, " of ", budget$max_operations,
            " operations and the ", what, " needs ", n, " more.\n",
            "  Fix: raise it with sd_client(budget = sd_budget(max_operations = N)), ",
            "or start a new client. The cap exists so a loop cannot drain your quota."
          ),
          call = NULL
        )
      )
    )
  }
  budget$state$used <- budget$state$used + n
  invisible(client)
}

# Refuse an oversized document. Uploads are free, so this runs after the upload
# and before anything billable.
sd_check_pages <- function(client, chunks_count, filename = "the document") {
  budget <- client$budget
  if (is.null(budget$max_pages) || is.null(chunks_count) || is.na(chunks_count)) {
    return(invisible(NULL))
  }
  pages <- ceiling(chunks_count / budget$chunks_per_page)
  if (pages > budget$max_pages) {
    stop(
      structure(
        class = c("sd_budget_error", "error", "condition"),
        list(
          message = paste0(
            filename, " parsed into ", chunks_count, " chunks, about ", pages,
            " pages at ", budget$chunks_per_page, " chunks per page. ",
            "The budget allows ", budget$max_pages, ".\n",
            "  Fix: raise max_pages in sd_budget(), tune chunks_per_page for this ",
            "document's density, or edit a shorter excerpt first."
          ),
          call = NULL
        )
      )
    )
  }
  invisible(pages)
}
