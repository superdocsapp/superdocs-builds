#' superdocsr: review-gated AI document editing for research papers
#'
#' A researcher-facing client for the SuperDocs document editing API. The
#' package covers one workflow end to end: render a paper, upload it, ask for
#' a targeted AI edit, inspect what the AI proposes, approve the parts you
#' agree with, and export the approved document.
#'
#' The whole point of the package is the gate in the middle. `sd_edit()`
#' defaults to `approval_mode = "ask_every_time"`, so the job pauses and waits;
#' nothing reaches the document until `sd_approve()` names the change ids you
#' accept. There is no function that approves everything for you.
#'
#' @section Cost controls:
#' Every client carries an [sd_budget()]. It caps how many billable operations
#' the client may spend and refuses documents above an estimated page count, so
#' a loop that goes wrong stops instead of draining a quota. `small_sample =
#' TRUE` is the cheap preset for a first run.
#'
#' @section Testing without a key:
#' The HTTP transport is a plain function stored on the client. Pass your own
#' to `sd_client(transport = )` and the package never touches the network --
#' that is how this package's own test suite and vignette run.
#'
#' @keywords internal
"_PACKAGE"
