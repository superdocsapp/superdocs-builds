approving_api <- function() {
  fake_api(
    "GET /v1/jobs/job_1" = function(n, req) {
      if (n == 1) job_awaiting_objects() else job_completed()
    },
    "POST /v1/chat/paper-2026/approve" = list(status = "ok")
  )
}

test_that("there is no approve-everything default", {
  client <- fake_client(approving_api())
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  expect_error(sd_approve(job), "Name the changes")
  expect_error(sd_approve(job), "no approve-everything default")
})

test_that("the request always carries a top-level approved field", {
  # Omitting it is a documented 422 even when every entry in `changes` has one.
  api <- approving_api()
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  sd_approve(job, c("ch_1", "ch_2"))
  body <- api$last("approve")$body

  expect_true("approved" %in% names(body))
  expect_true(body$approved)
  expect_equal(body$job_id, "job_1")
  expect_length(body$changes, 2)
  expect_equal(body$changes[[1]]$change_id, "ch_1")
  expect_true(body$changes[[2]]$approved)
})

test_that("the approval goes to the session's approve endpoint", {
  api <- approving_api()
  client <- fake_client(api)
  sd_approve(sd_job(client, "job_1", "paper-2026", status = "awaiting_approval"), "ch_1")

  expect_equal(api$last("approve")$path, "/v1/chat/paper-2026/approve")
  expect_equal(api$last("approve")$method, "POST")
})

test_that("approving refreshes the job so the caller sees what happened", {
  api <- fake_api(
    "GET /v1/jobs/job_1" = job_completed(),
    "POST /v1/chat/paper-2026/approve" = list(status = "ok")
  )
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  updated <- sd_approve(job, "ch_1")

  expect_equal(updated$status, "completed")
  expect_equal(api$n_calls("GET /v1/jobs/job_1"), 1)
})

test_that("denying sends approved = FALSE and the feedback", {
  api <- approving_api()
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  sd_deny(job, "ch_1", feedback = "Keep the hedge; the effect is not significant.")
  body <- api$last("approve")$body

  expect_false(body$approved)
  expect_false(body$changes[[1]]$approved)
  expect_equal(body$feedback, "Keep the hedge; the effect is not significant.")
})

test_that("duplicate and empty ids are cleaned up before sending", {
  api <- approving_api()
  client <- fake_client(api)
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  sd_approve(job, c("ch_1", "ch_1", NA, ""))
  expect_length(api$last("approve")$body$changes, 1)

  expect_error(sd_approve(job, character(0)), "nothing to decide")
  expect_error(sd_approve(job, c(NA_character_, "")), "nothing to decide")
})

test_that("approving a continue prompt is refused locally, not by a 409", {
  api <- fake_api(
    "GET /v1/jobs/job_1" = job_continue_prompt(),
    "POST /v1/chat/paper-2026/approve" = list(status = "ok")
  )
  client <- fake_client(api)
  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)

  expect_error(sd_approve(job, "ch_1"), "paused on a continue prompt")
  expect_equal(api$n_calls("approve"), 0)
})

test_that("approved must be a single TRUE or FALSE", {
  client <- fake_client(approving_api())
  job <- sd_job(client, "job_1", "paper-2026", status = "awaiting_approval")

  expect_error(sd_approve(job, "ch_1", approved = NA), "TRUE or FALSE")
  expect_error(sd_approve(job, "ch_1", approved = c(TRUE, FALSE)), "TRUE or FALSE")
})

test_that("a whole batch can be approved, but only by saying so", {
  api <- approving_api()
  client <- fake_client(api)
  job <- sd_wait(sd_job(client, "job_1", "paper-2026"), interval = 0.01, verbose = FALSE)
  changes <- sd_changes(job, refresh = FALSE)

  sd_approve(job, changes$change_id)
  expect_length(api$last("approve")$body$changes, nrow(changes))
})
