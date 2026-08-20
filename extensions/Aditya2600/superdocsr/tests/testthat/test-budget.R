test_that("small_sample is a genuinely cheap preset", {
  budget <- sd_budget(small_sample = TRUE)

  expect_equal(budget$max_operations, 1)
  expect_equal(budget$max_pages, 3)
  expect_true(budget$small_sample)
})

test_that("small_sample never loosens a stricter budget", {
  budget <- sd_budget(max_operations = 0, max_pages = 1, small_sample = TRUE)

  expect_equal(budget$max_operations, 0)
  expect_equal(budget$max_pages, 1)
})

test_that("an exhausted budget stops the request before it is sent", {
  api <- fake_api("POST /v1/chat/async" = job_completed())
  client <- fake_client(api, sd_budget(max_operations = 1))
  doc <- sd_document(client, session_id = "paper-2026")

  sd_edit(doc, "First edit.")
  expect_error(sd_edit(doc, "Second edit."), class = "sd_budget_error")

  # The refused edit must not have reached the network.
  expect_equal(api$n_calls("POST /v1/chat/async"), 1)
})

test_that("the budget error says how to raise the cap", {
  client <- fake_client(fake_api(), sd_budget(max_operations = 0))
  doc <- sd_document(client, session_id = "paper-2026")

  expect_error(sd_edit(doc, "Edit."), "sd_budget\\(max_operations = N\\)")
})

test_that("operation counters track spending", {
  api <- fake_api("POST /v1/chat/async" = job_completed())
  client <- fake_client(api, sd_budget(max_operations = 5))
  doc <- sd_document(client, session_id = "paper-2026")

  expect_equal(sd_ops_used(client), 0)
  expect_equal(sd_ops_remaining(client), 5)

  sd_edit(doc, "Edit.")

  expect_equal(sd_ops_used(client), 1)
  expect_equal(sd_ops_remaining(client), 4)
})

test_that("uploads and exports are free", {
  api <- fake_api(
    "POST /v1/documents/upload" = upload_payload(),
    "POST /v1/documents/export" = raw_response(charToRaw("PK bytes"))
  )
  client <- fake_client(api, sd_budget(max_operations = 0))
  path <- withr::local_tempfile(fileext = ".docx")

  doc <- sd_upload(test_docx(), client)
  sd_export(doc, "docx", path)

  expect_equal(sd_ops_used(client), 0)
})

test_that("an oversized document is refused before any edit runs", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload(chunks_count = 600L))
  client <- fake_client(api, sd_budget(max_pages = 5, chunks_per_page = 12))

  expect_error(sd_upload(test_docx(), client), class = "sd_budget_error")
  expect_error(sd_upload(test_docx(), client), "about 50 pages")
})

test_that("the page gate states its method and can be tuned", {
  api <- fake_api("POST /v1/documents/upload" = upload_payload(chunks_count = 600L))

  # 600 chunks at 12/page is 50 pages: refused at max_pages = 5.
  expect_error(
    sd_upload(test_docx(), fake_client(api, sd_budget(max_pages = 5))),
    "12 chunks per page"
  )

  # The same document at a denser 200 chunks/page is 3 pages: allowed.
  expect_s3_class(
    sd_upload(test_docx(), fake_client(api, sd_budget(max_pages = 5, chunks_per_page = 200))),
    "sd_document"
  )
})

test_that("sd_budget validates its arguments", {
  expect_error(sd_budget(max_operations = -1), "non-negative")
  expect_error(sd_budget(max_pages = 0), "NULL or a single number")
  expect_error(sd_budget(chunks_per_page = 0), "number >= 1")
})
