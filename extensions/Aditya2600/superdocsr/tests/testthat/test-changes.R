test_that("changes delivered as plain objects are read", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())
  client <- fake_client(api)

  changes <- sd_changes(sd_job(client, "job_1", "paper-2026"))

  expect_s3_class(changes, "sd_changes")
  expect_equal(nrow(changes), 1)
  expect_equal(changes$change_id, "ch_1")
  expect_equal(changes$operation, "edit")
  expect_equal(changes$ai_explanation, "Replaced an intensifier with the reported statistic")
})

test_that("a batch whose content is a JSON string is parsed a second time", {
  # This is the documented trap: `content` is JSON inside JSON. One parse leaves
  # it a character scalar and every field below reads as NA. If this test fails
  # with a table of NAs, the second fromJSON() call has gone missing.
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_batch_string())
  client <- fake_client(api)

  changes <- sd_changes(sd_job(client, "job_1", "paper-2026"))

  expect_equal(nrow(changes), 2)
  expect_equal(changes$change_id, c("ch_1", "ch_2"))
  expect_equal(changes$operation, c("edit", "create"))
  expect_false(any(is.na(changes$new_html)))
  expect_false(any(is.na(changes$ai_explanation)))
  expect_equal(changes$chunk_id[1], "550e8400-e29b-41d4-a716-446655440000")
})

test_that("the raw job body really does carry content as a string", {
  # Guards the fixture itself: if this stopped being a string, the test above
  # would pass for the wrong reason.
  body <- job_awaiting_batch_string()
  content <- body$metadata$intermediate_responses[[2]]$content

  expect_type(content, "character")
  expect_length(content, 1)
  expect_type(jsonlite::fromJSON(content, simplifyVector = FALSE)$changes, "list")
})

test_that("batch id and total come off the envelope onto every change", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_batch_string(batch_total = 32L))
  client <- fake_client(api)

  changes <- sd_changes(sd_job(client, "job_1", "paper-2026"))

  expect_equal(unique(changes$batch_id), "ch_1")
  expect_equal(unique(changes$batch_total), 32L)
})

test_that("the same change arriving by both routes is counted once", {
  body <- job_awaiting_batch_string(changes = list(a_change("ch_1")))
  body$metadata$pending_changes <- list(a_change("ch_1"), a_change("ch_9"))
  api <- fake_api("GET /v1/jobs/job_1" = body)

  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))

  expect_equal(sort(changes$change_id), c("ch_1", "ch_9"))
})

test_that("non-change intermediate events are ignored", {
  body <- job_awaiting_batch_string()
  body$metadata$intermediate_responses <- c(
    body$metadata$intermediate_responses,
    list(
      list(type = "model_fallback", content = "Falling back to core.", sequence = 3),
      list(type = "documents_changed", content = "{\"documents\": []}", sequence = 4)
    )
  )
  api <- fake_api("GET /v1/jobs/job_1" = body)

  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))
  expect_equal(nrow(changes), 2)
})

test_that("a batch with unparseable content warns and is skipped, not silently dropped", {
  body <- job_awaiting_objects()
  body$metadata$intermediate_responses <- list(
    list(type = "proposed_change_batch", content = "{not json", sequence = 2)
  )
  api <- fake_api("GET /v1/jobs/job_1" = body)

  expect_warning(
    changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026")),
    "not valid JSON"
  )
  # The well-formed change from pending_changes still comes through.
  expect_equal(changes$change_id, "ch_1")
})

test_that("no proposed changes is an honest empty table, not an error", {
  api <- fake_api("GET /v1/jobs/job_1" = job_completed())
  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))

  expect_equal(nrow(changes), 0)
  expect_named(
    changes,
    c(
      "change_id", "operation", "chunk_id", "document_id", "ai_explanation",
      "old_html", "new_html", "insert_after_chunk_id", "batch_id",
      "batch_total", "decided"
    )
  )
  expect_output(print(changes), "no changes proposed")
})

test_that("changes decided before a reconnect are marked", {
  body <- job_awaiting_batch_string()
  body$metadata$pending_batch_decisions <- list(ch_1 = list(approved = TRUE, feedback = NULL))
  api <- fake_api("GET /v1/jobs/job_1" = body)

  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))

  expect_equal(changes$decided, c(TRUE, FALSE))
})

test_that("missing optional fields become NA rather than shifting the table", {
  bare <- list(change_id = "ch_7", operation = "delete", chunk_id = "chunk-7")
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects(changes = list(bare)))

  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))

  expect_equal(changes$change_id, "ch_7")
  expect_true(is.na(changes$new_html))
  expect_true(is.na(changes$ai_explanation))
  expect_type(changes$batch_total, "integer")
})

test_that("printing a review never dumps raw HTML at the user", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())
  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))
  printed <- paste(capture.output(print(changes)), collapse = "\n")

  expect_false(grepl("<p>", printed, fixed = TRUE))
  expect_match(printed, "The effect was significant")
  expect_match(printed, "Nothing is applied until sd_approve")
})

test_that("a continue prompt is reported as such instead of as an empty review", {
  api <- fake_api("GET /v1/jobs/job_1" = job_continue_prompt())
  changes <- sd_changes(sd_job(fake_client(api), "job_1", "paper-2026"))

  expect_equal(nrow(changes), 0)
  expect_output(print(changes), "sd_continue")
})

test_that("refresh = FALSE reads the job in hand without another call", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())
  client <- fake_client(api)
  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)

  before <- api$n_calls()
  changes <- sd_changes(job, refresh = FALSE)

  expect_equal(api$n_calls(), before)
  expect_equal(nrow(changes), 1)
})
