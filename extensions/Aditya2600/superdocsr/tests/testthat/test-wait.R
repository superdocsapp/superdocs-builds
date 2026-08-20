test_that("polling continues until the job completes", {
  api <- fake_api("GET /v1/jobs/job_1" = function(n, req) {
    if (n < 3) job_in_progress() else job_completed()
  })
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "pending")

  done <- sd_wait(job, interval = 0.01, max_interval = 0.01, verbose = FALSE)

  expect_equal(done$status, "completed")
  expect_equal(done$result$response, "Done.")
  expect_equal(api$n_calls("GET /v1/jobs/job_1"), 3)
})

test_that("an already settled job is returned without a single poll", {
  api <- fake_api("GET /v1/jobs/job_1" = job_completed())
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "completed")

  expect_equal(sd_wait(job, verbose = FALSE)$status, "completed")
  expect_equal(api$n_calls(), 0)
})

test_that("awaiting_approval is a result, not something to wait out", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())
  client <- fake_client(api)

  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)

  expect_equal(job$status, "awaiting_approval")
  expect_equal(sd_awaiting_kind(job), "change_review")
  expect_equal(api$n_calls("GET /v1/jobs/job_1"), 1)
})

test_that("the two flavours of awaiting_approval are told apart", {
  api <- fake_api("GET /v1/jobs/job_1" = job_continue_prompt())
  client <- fake_client(api)

  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)
  expect_equal(sd_awaiting_kind(job), "continue_prompt")
})

test_that("backoff lengthens the gap between polls", {
  slow <- function(n, req) if (n < 4) job_in_progress() else job_completed()

  fixed_api <- fake_api("GET /v1/jobs/job_1" = slow)
  fixed_elapsed <- system.time(
    sd_wait(sd_job(fake_client(fixed_api), "job_1", "paper-2026"),
      interval = 0.02, backoff = FALSE, verbose = FALSE
    )
  )[["elapsed"]]

  backoff_api <- fake_api("GET /v1/jobs/job_1" = slow)
  backoff_elapsed <- system.time(
    sd_wait(sd_job(fake_client(backoff_api), "job_1", "paper-2026"),
      interval = 0.02, backoff = TRUE, max_interval = 10, verbose = FALSE
    )
  )[["elapsed"]]

  expect_equal(fixed_api$n_calls("GET /v1/jobs"), backoff_api$n_calls("GET /v1/jobs"))
  expect_gt(backoff_elapsed, fixed_elapsed)
})

test_that("a timeout is reported as a client give-up, not a server failure", {
  api <- fake_api("GET /v1/jobs/job_1" = job_in_progress())
  client <- fake_client(api)

  expect_error(
    sd_wait(sd_job(client, "job_1", "paper-2026"),
      timeout = 0.05, interval = 0.02, verbose = FALSE
    ),
    class = "sd_timeout_error"
  )
  expect_error(
    sd_wait(sd_job(client, "job_1", "paper-2026"),
      timeout = 0.05, interval = 0.02, verbose = FALSE
    ),
    "keeps running"
  )
})

test_that("a failed job raises rather than returning quietly", {
  api <- fake_api("GET /v1/jobs/job_1" = list(
    job_id = "job_1", session_id = "paper-2026", job_type = "chat",
    status = "failed", progress = 0,
    created_at = "t", updated_at = "t",
    error = "The model returned no usable edit."
  ))
  client <- fake_client(api)

  expect_error(
    sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE),
    class = "sd_job_failed"
  )
  expect_error(
    sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE),
    "no usable edit"
  )
})

test_that("sd_continue answers only a continue prompt", {
  api <- fake_api(
    "GET /v1/jobs/job_1" = function(n, req) if (n == 1) job_continue_prompt() else job_completed(),
    "POST /v1/chat/paper-2026/continue" = list(status = "resumed")
  )
  client <- fake_client(api)
  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)

  resumed <- sd_continue(job, proceed = TRUE)

  body <- api$last("continue")$body
  expect_equal(body$job_id, "job_1")
  expect_true(body[["continue"]])
  expect_equal(resumed$status, "completed")
})

test_that("sd_continue refuses a change review", {
  api <- fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())
  client <- fake_client(api)
  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)

  expect_error(sd_continue(job), "not paused on a continue prompt")
  expect_error(sd_continue(job), "sd_approve")
})

test_that("sd_cancel posts to the cancel endpoint", {
  api <- fake_api(
    "POST /v1/jobs/job_1/cancel" = list(status = "cancelling"),
    "GET /v1/jobs/job_1" = list(
      job_id = "job_1", session_id = "paper-2026", job_type = "chat",
      status = "cancelled", progress = 0, created_at = "t", updated_at = "t"
    )
  )
  client <- fake_client(api)

  cancelled <- sd_cancel(sd_job(client, "job_1", "paper-2026"))

  expect_equal(api$n_calls("POST /v1/jobs/job_1/cancel"), 1)
  expect_equal(cancelled$status, "cancelled")
})
