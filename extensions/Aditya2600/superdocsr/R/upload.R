# Getting a rendered paper into a SuperDocs session.

# The formats the API accepts as an editable document. Anything else comes back
# as a 415, so it is cheaper to say so here.
SD_UPLOAD_EXTS <- c("pdf", "docx", "txt", "rtf", "md", "html", "htm")

#' Upload a document into a SuperDocs session
#'
#' Sends a file to `POST /v1/documents/upload` and loads it as the session's
#' active editable document. The file is streamed from disk by `curl`, not read
#' into R first, so a large manuscript does not have to fit in memory twice.
#'
#' Uploading is not a billable operation. The page gate from [sd_budget()] is
#' applied here, right after the parse, because that is the first moment the
#' real chunk count is known and it is still before anything costs money.
#'
#' @param path Path to the file. One of `.pdf`, `.docx`, `.txt`, `.rtf`, `.md`,
#'   `.html`, `.htm`. Legacy binary `.doc` is not accepted -- convert it to
#'   `.docx` first.
#' @param client An [sd_client()].
#' @param session_id Session to load the document into. Generated if omitted.
#'   May contain only letters, digits, `_`, `-` and `.`, up to 256 characters.
#' @param open_mode `"replace"` (the default) swaps the session's focused
#'   document. `"new_focused"` opens the file as an extra document and focuses
#'   it; `"background"` opens it without stealing focus.
#'
#' @return An object of class `sd_document`.
#' @export
#' @examples
#' \dontrun{
#' client <- sd_client()
#' doc <- sd_upload("manuscript.docx", client)
#' doc
#' }
sd_upload <- function(path,
                      client = sd_client(),
                      session_id = NULL,
                      open_mode = c("replace", "new_focused", "background")) {
  sd_stopifnot_client(client)
  open_mode <- match.arg(open_mode)

  if (!is.character(path) || length(path) != 1L || is.na(path)) {
    stop("`path` must be a single file path.", call. = FALSE)
  }
  if (!file.exists(path)) {
    stop("No file at '", path, "'.\n  Fix: check the path, or render the source first with sd_knit().",
      call. = FALSE
    )
  }
  ext <- tolower(tools::file_ext(path))
  if (!ext %in% SD_UPLOAD_EXTS) {
    stop(
      "SuperDocs does not accept '.", ext, "' as an editable document.\n",
      "  Fix: use one of ", paste0(".", SD_UPLOAD_EXTS, collapse = ", "),
      if (identical(ext, "doc")) ". Convert legacy .doc to .docx first." else ".",
      call. = FALSE
    )
  }

  session_id <- sd_session_id_or_new(session_id)

  body <- list(
    file = curl::form_file(path),
    session_id = session_id
  )
  if (!identical(open_mode, "replace")) {
    body$open_mode <- open_mode
  }

  req <- sd_req(client, "/v1/documents/upload", method = "POST")
  req <- do.call(httr2::req_body_multipart, c(list(req), body))
  parsed <- sd_json(sd_perform(client, req))

  doc <- sd_document(
    client = client,
    session_id = parsed$session_id %||% session_id,
    filename = parsed$filename %||% basename(path),
    chunks_count = sd_as_int(parsed$chunks_count),
    version_id = parsed$version_id %||% NA_character_,
    html = parsed$html %||% NA_character_,
    page_setup = parsed$page_setup,
    source_path = path
  )

  sd_check_pages(client, doc$chunks_count, filename = doc$filename)
  doc
}

#' A document open in a SuperDocs session
#'
#' Constructor for the object [sd_upload()] returns. You rarely call this
#' directly; use it when you already hold a session id -- to resume work after
#' a crash, say -- and want the other verbs to accept it.
#'
#' @param client An [sd_client()].
#' @param session_id Session holding the document.
#' @param filename Name reported by the API.
#' @param chunks_count Number of addressable blocks the parser found.
#' @param version_id Version identifier reported by the API.
#' @param html Parsed document HTML, when the API returned it.
#' @param page_setup Page geometry list, or `NULL` for formats that carry none.
#' @param source_path Local file the document came from, if any.
#'
#' @return An object of class `sd_document`.
#' @export
#' @examples
#' client <- sd_client(api_key = "sk_x", transport = function(req) req)
#' sd_document(client, session_id = "paper-2026")
sd_document <- function(client,
                        session_id,
                        filename = NA_character_,
                        chunks_count = NA_integer_,
                        version_id = NA_character_,
                        html = NA_character_,
                        page_setup = NULL,
                        source_path = NA_character_) {
  sd_stopifnot_client(client)
  structure(
    list(
      client = client,
      session_id = sd_check_session_id(session_id),
      filename = filename,
      chunks_count = chunks_count,
      version_id = version_id,
      html = html,
      page_setup = page_setup,
      source_path = source_path
    ),
    class = "sd_document"
  )
}

#' @export
print.sd_document <- function(x, ...) {
  cat("<sd_document>\n")
  cat("  session:  ", x$session_id, "\n", sep = "")
  cat("  file:     ", x$filename, "\n", sep = "")
  if (!is.na(x$chunks_count)) {
    cat("  chunks:   ", x$chunks_count, "\n", sep = "")
  }
  if (!is.null(x$page_setup$orientation)) {
    cat("  page:     ", x$page_setup$orientation, " ",
      x$page_setup$width_in %||% "?", "in x ",
      x$page_setup$height_in %||% "?", "in\n",
      sep = ""
    )
  }
  invisible(x)
}

# ---- internals --------------------------------------------------------------

sd_check_session_id <- function(session_id) {
  if (!is.character(session_id) || length(session_id) != 1L || is.na(session_id)) {
    stop("`session_id` must be a single string.", call. = FALSE)
  }
  # Checked in two parts: TRE caps a {n,m} bound at 255, and the limit is 256.
  if (!grepl("^[A-Za-z0-9_.-]+$", session_id) || nchar(session_id) > 256L) {
    stop(
      "'", session_id, "' is not a valid session id.\n",
      "  Fix: use only letters, digits, '_', '-' and '.', up to 256 characters. ",
      "Spaces and slashes are rejected by the API with a 422.",
      call. = FALSE
    )
  }
  session_id
}

sd_session_id_or_new <- function(session_id) {
  if (is.null(session_id)) {
    return(sprintf(
      "superdocsr-%s-%04d",
      format(Sys.time(), "%Y%m%d-%H%M%S"),
      sample.int(9999, 1)
    ))
  }
  sd_check_session_id(session_id)
}

sd_as_int <- function(x) {
  if (is.null(x)) NA_integer_ else as.integer(x)
}

# Every verb downstream of upload accepts a document, a job, or a bare session
# id. One accessor, so none of them has to care.
sd_session_of <- function(x) {
  if (inherits(x, c("sd_document", "sd_job"))) {
    return(x$session_id)
  }
  if (is.character(x) && length(x) == 1L) {
    return(sd_check_session_id(x))
  }
  stop("Expected an sd_document, an sd_job, or a session id string.", call. = FALSE)
}

sd_client_of <- function(x, client = NULL) {
  if (!is.null(client)) {
    sd_stopifnot_client(client)
    return(client)
  }
  if (inherits(x, c("sd_document", "sd_job"))) {
    return(x$client)
  }
  stop("No client available.\n  Fix: pass `client = sd_client()`.", call. = FALSE)
}
