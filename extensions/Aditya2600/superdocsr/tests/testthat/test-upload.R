test_that("a successful upload returns the parsed document", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  doc <- sd_upload(test_docx(), fake_client(api), session_id = "paper-2026")

  expect_s3_class(doc, "sd_document")
  expect_equal(doc$session_id, "paper-2026")
  expect_equal(doc$filename, "manuscript.docx")
  expect_equal(doc$chunks_count, 12L)
  expect_equal(doc$page_setup$orientation, "portrait")
})

test_that("the upload is multipart and carries the session", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  sd_upload(test_docx(), fake_client(api), session_id = "paper-2026")
  call <- api$last()

  expect_equal(call$path, "/v1/documents/upload")
  expect_equal(call$method, "POST")
  expect_equal(call$body$session_id, "paper-2026")
  # The file rides as a curl form_file, i.e. streamed from disk, not read in.
  expect_s3_class(call$body$file, "form_file")
})

test_that("open_mode is sent only when it is not the default", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  client <- fake_client(api)

  sd_upload(test_docx(), client, session_id = "s1")
  expect_null(api$last()$body$open_mode)

  sd_upload(test_docx(), client, session_id = "s1", open_mode = "background")
  expect_equal(api$last()$body$open_mode, "background")
})

test_that("a missing file is caught before a request is sent", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  expect_error(sd_upload("no-such-file.docx", fake_client(api)), "No file at")
  expect_equal(api$n_calls(), 0)
})

test_that("unsupported extensions are caught locally, with the .doc case named", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  client <- fake_client(api)

  csv <- withr::local_tempfile(fileext = ".csv")
  writeBin(charToRaw("a,b"), csv)
  expect_error(sd_upload(csv, client), "does not accept '\\.csv'")

  doc <- withr::local_tempfile(fileext = ".doc")
  writeBin(charToRaw("legacy"), doc)
  expect_error(sd_upload(doc, client), "Convert legacy \\.doc to \\.docx")

  expect_equal(api$n_calls(), 0)
})

test_that("session ids are validated against the documented pattern", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  client <- fake_client(api)

  expect_error(sd_upload(test_docx(), client, session_id = "has spaces"), "not a valid session id")
  expect_error(sd_upload(test_docx(), client, session_id = "has/slash"), "422")
  expect_equal(api$n_calls(), 0)
})

test_that("a generated session id satisfies the same pattern", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload())
  sd_upload(test_docx(), fake_client(api))

  expect_match(api$last()$body$session_id, "^[A-Za-z0-9_.-]+$")
})

test_that("sd_document accepts a session id for resuming work", {
  client <- fake_client(fake_api())
  doc <- sd_document(client, session_id = "paper-2026")

  expect_equal(doc$session_id, "paper-2026")
  expect_output(print(doc), "paper-2026")
})
