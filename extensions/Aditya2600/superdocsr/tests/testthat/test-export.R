export_bytes <- function() as.raw(c(0x50, 0x4b, 0x03, 0x04, 0x14, 0x00))

test_that("an export writes real bytes and returns the path", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)
  path <- withr::local_tempfile(fileext = ".docx")

  written <- sd_export(sd_document(client, "paper-2026"), "docx", path)

  expect_equal(written, path)
  expect_true(file.exists(path))
  expect_equal(readBin(path, "raw", 6), export_bytes())
})

test_that("the request names the session and the format", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)

  sd_export(sd_document(client, "paper-2026"), "pdf",
    withr::local_tempfile(fileext = ".pdf"),
    options = list(paper_size = "A4", watermark_text = "DRAFT")
  )
  body <- api$last()$body

  expect_equal(body$session_id, "paper-2026")
  expect_equal(body$format, "pdf")
  expect_equal(body$options$paper_size, "A4")
})

test_that("options are omitted when empty rather than sent as an empty object", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)

  sd_export(sd_document(client, "paper-2026"), "docx", withr::local_tempfile(fileext = ".docx"))
  expect_false("options" %in% names(api$last()$body))
})

test_that("the default path follows the document name and the format", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)
  withr::local_dir(withr::local_tempdir())

  doc <- sd_document(client, "paper-2026", filename = "manuscript.docx")

  expect_equal(basename(sd_export(doc, "markdown")), "manuscript.md")
  expect_equal(basename(sd_export(doc, "docx")), "manuscript.docx")
})

test_that("only real export formats are accepted", {
  client <- fake_client(fake_api())
  doc <- sd_document(client, "paper-2026")

  expect_error(sd_export(doc, "rtf"), "not an export target")
  expect_error(sd_export(doc, "epub"), "must be one of")
})

test_that("an empty body is an error, not a zero-byte success", {
  api <- fake_api("POST /v1/documents/export" = raw_response(raw()))
  client <- fake_client(api)

  expect_error(
    sd_export(sd_document(client, "paper-2026"), "docx", withr::local_tempfile(fileext = ".docx")),
    "empty body"
  )
})

test_that("non-fatal render warnings are surfaced", {
  warnings <- jsonlite::toJSON(
    list(list(
      code = "image_download_failed",
      message = "figure-2.png could not be fetched",
      detail = list(src = "https://example.test/figure-2.png")
    )),
    auto_unbox = TRUE
  )
  api <- fake_api("POST /v1/documents/export" = raw_response(
    export_bytes(),
    headers = list(`X-Export-Warnings` = jsonlite::base64_enc(charToRaw(warnings)))
  ))
  client <- fake_client(api)
  path <- withr::local_tempfile(fileext = ".docx")

  expect_warning(
    sd_export(sd_document(client, "paper-2026"), "docx", path),
    "image_download_failed"
  )
  # The file is still written; the warning is about fidelity, not failure.
  expect_true(file.exists(path))
})

test_that("exporting mid-review says the pending changes are not in the file", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  expect_warning(
    sd_export(job, "docx", withr::local_tempfile(fileext = ".docx")),
    "still awaiting approval"
  )
})

test_that("missing directories are created", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)
  path <- file.path(withr::local_tempdir(), "nested", "out", "paper.docx")

  expect_true(file.exists(sd_export(sd_document(client, "paper-2026"), "docx", path)))
})

test_that("a bare session id is enough to export", {
  api <- fake_api("POST /v1/documents/export" = raw_response(export_bytes()))
  client <- fake_client(api)

  path <- sd_export("paper-2026",
    "docx",
    withr::local_tempfile(fileext = ".docx"),
    client = client
  )
  expect_true(file.exists(path))
})
