# Client construction, request building, and the single place every HTTP call
# in this package goes through.

#' Create a SuperDocs client
#'
#' Builds the object every other `sd_*()` function takes. It holds the API key,
#' the base URL, the spending [sd_budget()], and the HTTP transport.
#'
#' The transport is a function of one argument -- an `httr2` request -- that
#' returns an `httr2` response. It defaults to [httr2::req_perform()]. Supplying
#' your own is how you run this package with no network and no API key; the
#' test suite and the package vignette both do exactly that.
#'
#' @param api_key SuperDocs API key (the `sk_` key from Settings > API Keys).
#'   Read from the `SUPERDOCS_API_KEY` environment variable by default. Never
#'   type it into a script that goes into version control.
#' @param base_url Base URL of the API. Defaults to `https://api.superdocs.app`.
#' @param budget An [sd_budget()] controlling how much this client may spend.
#' @param transport `NULL` (perform real requests) or a function taking an
#'   `httr2` request and returning an `httr2` response.
#' @param timeout Per-request timeout in seconds. This is the transport
#'   timeout, not the wall-clock budget for an AI edit -- that one belongs to
#'   [sd_wait()].
#' @param max_tries Number of attempts for transient failures (429 and 5xx).
#'   `Retry-After` is honoured when the server sends it.
#'
#' @return An object of class `sd_client`.
#' @export
#' @examples
#' # Offline client: a transport that answers every request the same way.
#' fake <- function(req) {
#'   httr2::response(
#'     status_code = 200,
#'     headers = list(`Content-Type` = "application/json"),
#'     body = charToRaw("[]")
#'   )
#' }
#' client <- sd_client(api_key = "sk_not_a_real_key", transport = fake)
#' client
#'
#' \dontrun{
#' # Real client, key from the environment.
#' client <- sd_client()
#' sd_verify_key(client)
#' }
sd_client <- function(api_key = Sys.getenv("SUPERDOCS_API_KEY"),
                      base_url = "https://api.superdocs.app",
                      budget = sd_budget(),
                      transport = NULL,
                      timeout = 60,
                      max_tries = 3) {
  if (!is.character(api_key) || length(api_key) != 1L || is.na(api_key)) {
    stop("`api_key` must be a single string.", call. = FALSE)
  }
  if (!nzchar(api_key) && is.null(transport)) {
    stop(
      "No API key found.\n",
      "  Cause: `api_key` is empty and no `SUPERDOCS_API_KEY` is set.\n",
      "  Fix:   Sys.setenv(SUPERDOCS_API_KEY = \"sk_...\") in ~/.Renviron, ",
      "or pass `transport =` to run offline.",
      call. = FALSE
    )
  }
  if (!inherits(budget, "sd_budget")) {
    stop("`budget` must come from sd_budget().", call. = FALSE)
  }
  if (!is.null(transport) && !is.function(transport)) {
    stop("`transport` must be NULL or a function of one argument.", call. = FALSE)
  }

  structure(
    list(
      api_key = api_key,
      base_url = sub("/+$", "", base_url),
      budget = budget,
      transport = transport %||% httr2::req_perform,
      timeout = timeout,
      max_tries = max_tries,
      user_agent = sprintf(
        "superdocsr/%s (R %s.%s)",
        utils::packageVersion("superdocsr"),
        R.version$major, R.version$minor
      )
    ),
    class = "sd_client"
  )
}

#' @export
print.sd_client <- function(x, ...) {
  cat("<sd_client>\n")
  cat("  base url:  ", x$base_url, "\n", sep = "")
  cat("  api key:   ", sd_mask_key(x$api_key), "\n", sep = "")
  cat("  transport: ", if (identical(x$transport, httr2::req_perform)) {
    "httr2::req_perform (live)"
  } else {
    "custom (offline)"
  }, "\n", sep = "")
  print(x$budget)
  invisible(x)
}

#' Confirm an API key works
#'
#' Calls `GET /v1/sessions`, which the SuperDocs documentation names as the
#' cheapest way to check an `sk_` key. It is not billable and it does not
#' create anything. `GET /v1/users/me` is deliberately not used here: it is
#' web-app-only and returns 401 even for a valid API key.
#'
#' @param client An [sd_client()].
#' @return `TRUE`, invisibly, if the key is accepted. Errors otherwise.
#' @export
#' @examples
#' \dontrun{
#' sd_verify_key(sd_client())
#' }
sd_verify_key <- function(client) {
  sd_stopifnot_client(client)
  sd_perform(client, sd_req(client, "/v1/sessions"))
  invisible(TRUE)
}

# ---- internals --------------------------------------------------------------

`%||%` <- function(x, y) if (is.null(x)) y else x

sd_mask_key <- function(key) {
  if (!nzchar(key)) {
    return("<none>")
  }
  if (nchar(key) <= 8) {
    return(strrep("*", nchar(key)))
  }
  paste0(substr(key, 1, 5), strrep("*", nchar(key) - 8), substr(key, nchar(key) - 2, nchar(key)))
}

sd_stopifnot_client <- function(client) {
  if (!inherits(client, "sd_client")) {
    stop("`client` must come from sd_client().", call. = FALSE)
  }
  invisible(TRUE)
}

sd_is_transient <- function(resp) {
  httr2::resp_status(resp) %in% c(429L, 500L, 502L, 503L, 504L)
}

# Build a request. Errors are never raised by httr2 itself: sd_perform() maps
# them so every failure in this package speaks with one voice.
sd_req <- function(client, path, method = "GET") {
  httr2::request(client$base_url) |>
    httr2::req_url_path_append(path) |>
    httr2::req_method(method) |>
    httr2::req_auth_bearer_token(client$api_key) |>
    httr2::req_user_agent(client$user_agent) |>
    httr2::req_timeout(client$timeout) |>
    httr2::req_retry(
      max_tries = client$max_tries,
      is_transient = sd_is_transient
    ) |>
    httr2::req_error(is_error = function(resp) FALSE)
}

sd_perform <- function(client, req) {
  resp <- client$transport(req)
  if (!inherits(resp, "httr2_response")) {
    stop(
      "The transport returned a ", class(resp)[1], ", not an httr2 response.\n",
      "  Fix: a transport must return httr2::response(...).",
      call. = FALSE
    )
  }
  sd_check_status(resp, req)
  resp
}

# Parse a JSON body without simplification. Keeping lists as lists is what makes
# the second parse in sd_changes() predictable: no silent matrix coercion, no
# fields quietly dropped because one element of a batch lacked them.
sd_json <- function(resp) {
  txt <- httr2::resp_body_string(resp)
  if (!nzchar(txt)) {
    return(list())
  }
  jsonlite::fromJSON(txt, simplifyVector = FALSE)
}

sd_check_status <- function(resp, req = NULL) {
  status <- httr2::resp_status(resp)
  if (status < 400L) {
    return(invisible(resp))
  }

  detail <- sd_error_detail(resp)
  fix <- sd_error_fix(status)
  msg <- paste0(
    "SuperDocs API error ", status, ".\n",
    "  Cause: ", detail, "\n",
    "  Fix:   ", fix
  )

  cond <- structure(
    class = c(paste0("sd_http_", status), "sd_api_error", "error", "condition"),
    list(
      message = msg,
      call = NULL,
      status = status,
      detail = detail,
      url = if (is.null(req)) NA_character_ else req$url
    )
  )
  stop(cond)
}

# The documented error envelope is {"detail": ...}, but `detail` is a string on
# most endpoints, an object on 413, and an array of validation records on 422.
# All three shapes end up as one readable line.
sd_error_detail <- function(resp) {
  parsed <- tryCatch(sd_json(resp), error = function(e) NULL)
  if (is.null(parsed)) {
    body <- tryCatch(httr2::resp_body_string(resp), error = function(e) "")
    if (!nzchar(body)) {
      return("no response body (the gateway may have rejected the request)")
    }
    return(substr(gsub("\\s+", " ", body), 1, 300))
  }
  detail <- parsed$detail %||% parsed$message_user %||% parsed
  sd_flatten_detail(detail)
}

sd_flatten_detail <- function(detail) {
  if (is.character(detail) && length(detail) == 1L) {
    return(detail)
  }
  if (is.list(detail) && !is.null(detail$message_user)) {
    return(as.character(detail$message_user))
  }
  if (is.list(detail) && !is.null(detail$msg)) {
    return(as.character(detail$msg))
  }
  if (is.list(detail)) {
    parts <- vapply(detail, function(entry) {
      if (is.list(entry) && !is.null(entry$msg)) {
        loc <- paste(unlist(entry$loc %||% list()), collapse = ".")
        if (nzchar(loc)) paste0(loc, ": ", entry$msg) else as.character(entry$msg)
      } else {
        paste(utils::capture.output(utils::str(entry)), collapse = " ")
      }
    }, character(1))
    return(paste(parts, collapse = "; "))
  }
  paste(as.character(detail), collapse = "; ")
}

sd_error_fix <- function(status) {
  switch(as.character(status),
    "400" = "Check the request fields; an empty instruction is the usual cause.",
    "401" = "The key was rejected. Check SUPERDOCS_API_KEY, and note that a key revoked in Settings stays revoked.",
    "403" = "The account does not own this session or document.",
    "404" = "Jobs are deleted one hour after they are created. Re-run the edit rather than polling a stale job_id.",
    "409" = "Another job is running on this session, or a review is still pending. Resolve it, then retry.",
    "413" = "The payload is over the size cap. Split the document, or export via the pre-signed upload path.",
    "415" = "Unsupported file type. Use .pdf, .docx, .txt, .rtf, .md, .html or .htm; convert legacy .doc to .docx first.",
    "422" = "The request body did not validate. Session ids may only contain letters, digits, '_', '-' and '.'.",
    "429" = "The monthly operation quota is exhausted, or you are being throttled. Wait for Retry-After, or upgrade the plan.",
    "500" = "Server error. Retry; if it persists, report it to hello@superdocs.app with the request time.",
    "504" = "The edit ran past the 30 minute server cap. Split it into smaller instructions, one section at a time.",
    "Check the SuperDocs API documentation at https://docs.superdocs.app."
  )
}
