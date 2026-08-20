test_that("review is the default: every async edit asks before it applies", {
  api <- fake_api("POST /v1/chat/async" = list(
    job_id = "job_1", session_id = "paper-2026", status = "pending"
  ))
  client <- fake_client(api)

  job <- sd_edit(sd_document(client, "paper-2026"), "Tighten the abstract.")

  expect_equal(api$last()$body$approval_mode, "ask_every_time")
  expect_s3_class(job, "sd_job")
  expect_equal(job$job_id, "job_1")
  expect_equal(job$status, "pending")
})

test_that("auto-apply has to be asked for by name", {
  api <- fake_api("POST /v1/chat/async" = list(
    job_id = "job_1", session_id = "paper-2026", status = "pending"
  ))
  client <- fake_client(api)

  sd_edit(sd_document(client, "paper-2026"), "Tighten it.", approval_mode = "approve_all")
  expect_equal(api$last()$body$approval_mode, "approve_all")
})

test_that("a synchronous edit cannot pretend to offer a review", {
  client <- fake_client(fake_api())

  expect_error(
    sd_edit(sd_document(client, "paper-2026"), "Tighten it.", async = FALSE),
    "cannot pause for review"
  )
  expect_error(
    sd_edit(sd_document(client, "paper-2026"), "Tighten it.", async = FALSE),
    "approval_mode = \"approve_all\""
  )
})

test_that("a synchronous edit returns a job that is already finished", {
  api <- fake_api("POST /v1/chat" = list(
    response = "Done.",
    session_id = "paper-2026",
    document_changes = list(updated_html = "<p>edited</p>")
  ))
  client <- fake_client(api)

  job <- sd_edit(
    sd_document(client, "paper-2026"), "Tighten it.",
    async = FALSE, approval_mode = "approve_all"
  )

  expect_equal(job$status, "completed")
  expect_true(is.na(job$job_id))
  expect_equal(job$result$response, "Done.")
  expect_null(api$last()$body$approval_mode)
})

test_that("a finished synchronous job needs no polling and cannot be approved", {
  api <- fake_api("POST /v1/chat" = list(response = "Done.", session_id = "paper-2026"))
  client <- fake_client(api)
  job <- sd_edit(
    sd_document(client, "paper-2026"), "Tighten it.",
    async = FALSE, approval_mode = "approve_all"
  )

  # Already settled, so sd_wait() hands it straight back without a poll.
  expect_equal(sd_wait(job, verbose = FALSE)$status, "completed")
  expect_equal(api$n_calls("GET"), 0)

  expect_error(sd_approve(job, "ch_1"), "nothing to approve")
  expect_error(sd_approve(job, "ch_1"), "no review stage to gate")
})

test_that("an unsettled job with no id says why it cannot be polled", {
  client <- fake_client(fake_api())
  job <- sd_job(client, job_id = NULL, session_id = "paper-2026", status = "in_progress")

  expect_error(sd_wait(job, verbose = FALSE), "no job_id")
})

test_that("an empty instruction is refused locally", {
  api <- fake_api("POST /v1/chat/async" = list(job_id = "j", session_id = "s", status = "pending"))
  client <- fake_client(api)

  expect_error(sd_edit(sd_document(client, "paper-2026"), "   "), "non-empty string")
  expect_equal(api$n_calls(), 0)
})

test_that("model options are validated locally rather than by a 422", {
  client <- fake_client(fake_api())
  doc <- sd_document(client, "paper-2026")

  expect_error(sd_edit(doc, "Edit.", model_tier = "ultra"), "model_tier")
  expect_error(sd_edit(doc, "Edit.", thinking_depth = "medium"), "thinking_depth")
  expect_error(sd_edit(doc, "Edit.", response_mode = "tiny"), "response_mode")
})

test_that("a small_sample budget picks the cheapest model tier by default", {
  api <- fake_api("POST /v1/chat/async" = list(job_id = "j", session_id = "s", status = "pending"))
  client <- fake_client(api, sd_budget(small_sample = TRUE))

  sd_edit(sd_document(client, "paper-2026"), "Edit.")
  expect_equal(api$last()$body$model_tier, "turbo")
})

test_that("an explicit model tier still wins under small_sample", {
  api <- fake_api("POST /v1/chat/async" = list(job_id = "j", session_id = "s", status = "pending"))
  client <- fake_client(api, sd_budget(small_sample = TRUE))

  sd_edit(sd_document(client, "paper-2026"), "Edit.", model_tier = "max")
  expect_equal(api$last()$body$model_tier, "max")
})

test_that("document_html is omitted unless it is given", {
  api <- fake_api("POST /v1/chat/async" = list(job_id = "j", session_id = "s", status = "pending"))
  client <- fake_client(api)

  sd_edit(sd_document(client, "paper-2026"), "Edit.")
  expect_false("document_html" %in% names(api$last()$body))

  sd_edit(sd_document(client, "paper-2026"), "Edit.", document_html = "<p>x</p>")
  expect_equal(api$last()$body$document_html, "<p>x</p>")
})
