# Getting the approved document back out as a file.

SD_EXPORT_FORMATS <- c("docx", "pdf", "html", "markdown", "txt")

SD_EXPORT_EXT <- c(
  docx = "docx", pdf = "pdf", html = "html",
  markdown = "md", txt = "txt"
)

#' Export a document to a file
#'
#' Renders the session's current document through `POST /v1/documents/export`
#' and writes the bytes to disk. Exports are not billable, so exporting often
#' is free -- do it after every approved round rather than at the end.
#'
#' What gets exported is what is *in* the document. Changes still awaiting
#' approval are not in it, and this function says so rather than letting a
#' successful-looking export imply otherwise.
#'
#' @param document An [sd_document()], an [sd_job()], or a session id.
#' @param format One of `"docx"` (default), `"pdf"`, `"html"`, `"markdown"`,
#'   `"txt"`. RTF is an upload format only; it is not an export target.
#' @param path Where to write the file. Defaults to the document's name with
#'   the format's extension, in the working directory.
#' @param options Named list of export options passed through to the API:
#'   `paper_size`, `orientation`, `margins`, `custom_margins_inches`,
#'   `filename`, `embed_images`, `watermark_text`, `watermark_opacity`.
#' @param client An [sd_client()]. Taken from `document` when it has one.
#'
#' @return The path written, invisibly. Raises an error if the response was
#'   empty, so a returned path always means a real file.
#' @export
#' @examples
#' \dontrun{
#' sd_export(doc, "docx", "manuscript-revised.docx")
#' sd_export(doc, "pdf", "manuscript-revised.pdf",
#'   options = list(paper_size = "A4", margins = "narrow")
#' )
#' }
sd_export <- function(document,
                      format = "docx",
                      path = NULL,
                      options = list(),
                      client = NULL) {
  client <- sd_client_of(document, client)
  session_id <- sd_session_of(document)

  if (!is.character(format) || length(format) != 1L || !format %in% SD_EXPORT_FORMATS) {
    stop(
      "`format` must be one of ", paste0("\"", SD_EXPORT_FORMATS, "\"", collapse = ", "), ".\n",
      "  Note: RTF is accepted as an upload but is not an export target.",
      call. = FALSE
    )
  }
  if (!is.list(options)) {
    stop("`options` must be a named list.", call. = FALSE)
  }

  if (inherits(document, "sd_job") && identical(document$status, "awaiting_approval")) {
    warning(
      "This job is still awaiting approval. Pending changes are not in the document, ",
      "so the exported file will not contain them.",
      call. = FALSE
    )
  }

  path <- path %||% sd_default_export_path(document, format)

  body <- sd_drop_null(list(
    session_id = session_id,
    format = format,
    options = if (length(options)) options else NULL
  ))
  req <- httr2::req_body_json(
    sd_req(client, "/v1/documents/export", method = "POST"), body
  )
  resp <- sd_perform(client, req)

  bytes <- httr2::resp_body_raw(resp)
  if (length(bytes) == 0L) {
    stop(
      "The export returned an empty body, so no file was written.\n",
      "  Fix: check the session still holds a document (sd_upload() it again if not).",
      call. = FALSE
    )
  }

  dir <- dirname(path)
  if (!dir.exists(dir)) {
    dir.create(dir, recursive = TRUE)
  }
  writeBin(bytes, path)

  written <- file.size(path)
  if (is.na(written) || written == 0L) {
    stop("Wrote '", path, "' but it is empty. The disk write failed.", call. = FALSE)
  }

  sd_report_export_warnings(resp)
  invisible(path)
}

# ---- internals --------------------------------------------------------------

sd_default_export_path <- function(document, format) {
  base <- if (inherits(document, "sd_document") && !is.na(document$filename)) {
    tools::file_path_sans_ext(document$filename)
  } else {
    sd_session_of(document)
  }
  paste0(base, ".", SD_EXPORT_EXT[[format]])
}

# Non-fatal render problems ride back in a base64-encoded JSON header. A silent
# export that dropped an image is exactly the kind of quiet lie worth surfacing.
sd_report_export_warnings <- function(resp) {
  header <- httr2::resp_header(resp, "X-Export-Warnings")
  if (is.null(header) || !nzchar(header)) {
    return(invisible(NULL))
  }
  parsed <- tryCatch(
    jsonlite::fromJSON(rawToChar(jsonlite::base64_dec(header)), simplifyVector = FALSE),
    error = function(e) NULL
  )
  if (is.null(parsed) || length(parsed) == 0L) {
    return(invisible(NULL))
  }
  lines <- vapply(parsed, function(w) {
    paste0("  - ", w$code %||% "warning", ": ", w$message %||% "")
  }, character(1))
  warning(
    "The export completed with non-fatal warnings:\n",
    paste(lines, collapse = "\n"),
    call. = FALSE
  )
  invisible(parsed)
}
