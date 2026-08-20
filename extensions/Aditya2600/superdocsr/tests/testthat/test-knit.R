# sd_knit() renders for real, then runs the workflow against the fake API.
# Rendering needs pandoc, so these skip where pandoc is absent rather than
# failing for a reason that has nothing to do with this package.

skip_without_pandoc <- function() {
  skip_if_not_installed("rmarkdown")
  skip_if_not(rmarkdown::pandoc_available(), "pandoc is not available")
}

a_paper <- function(env = parent.frame()) {
  dir <- withr::local_tempdir(.local_envir = env)
  path <- file.path(dir, "paper.Rmd")
  writeLines(
    c(
      "---",
      "title: A Small Paper",
      "---",
      "",
      "# Results",
      "",
      "The effect was very significant."
    ),
    path
  )
  path
}

knit_api <- function() {
  fake_api(
    "POST /v1/documents/upload" = upload_payload(filename = "paper.md", chunks_count = 6L),
    "POST /v1/chat/async" = list(job_id = "job_1", session_id = "paper-2026", status = "pending"),
    "GET /v1/jobs/job_1" = function(n, req) {
      if (n == 1) job_awaiting_batch_string() else job_completed()
    },
    "POST /v1/chat/paper-2026/approve" = list(status = "ok"),
    "POST /v1/documents/export" = raw_response(as.raw(c(0x50, 0x4b)))
  )
}

test_that("sd_knit renders, edits, reviews, approves and exports", {
  skip_without_pandoc()
  api <- knit_api()
  client <- fake_client(api)
  out <- file.path(withr::local_tempdir(), "paper-revised.docx")

  result <- sd_knit(
    a_paper(),
    "Replace the intensifier with the reported statistic.",
    output_format = "md_document",
    client = client,
    review = function(changes) changes$change_id[changes$operation == "edit"],
    export_path = out,
    timeout = 5
  )

  expect_s3_class(result, "sd_knit_result")
  expect_true(file.exists(result$rendered))
  expect_equal(result$approved, "ch_1")
  expect_equal(result$denied, "ch_2")
  expect_equal(result$export_path, out)
  expect_true(file.exists(out))
})

test_that("every proposed change gets a decision, so nothing is left blocking", {
  skip_without_pandoc()
  api <- knit_api()

  result <- sd_knit(a_paper(), "Tighten it.",
    output_format = "md_document",
    client = fake_client(api),
    review = function(changes) changes$change_id[1],
    timeout = 5
  )

  decided <- c(result$approved, result$denied)
  expect_setequal(decided, result$changes$change_id)
})

test_that("a review that returns NULL leaves the job open and approves nothing", {
  skip_without_pandoc()
  api <- knit_api()

  result <- NULL
  expect_message(
    result <- sd_knit(a_paper(), "Tighten it.",
      output_format = "md_document",
      client = fake_client(api),
      review = sd_review_none,
      export_path = file.path(withr::local_tempdir(), "out.docx"),
      timeout = 5
    ),
    "Review left open"
  )

  expect_length(result$approved, 0)
  expect_equal(api$n_calls("approve"), 0)
  expect_equal(api$n_calls("export"), 0)
  expect_null(result$export_path)
  expect_equal(result$job$status, "awaiting_approval")
})

test_that("a review that returns character(0) denies everything", {
  skip_without_pandoc()
  api <- knit_api()

  result <- sd_knit(a_paper(), "Tighten it.",
    output_format = "md_document",
    client = fake_client(api),
    review = function(changes) character(0),
    timeout = 5
  )

  expect_length(result$approved, 0)
  expect_setequal(result$denied, c("ch_1", "ch_2"))
  expect_false(api$last("approve")$body$approved)
})

test_that("nothing approved means nothing exported", {
  skip_without_pandoc()
  api <- knit_api()

  expect_message(
    sd_knit(a_paper(), "Tighten it.",
      output_format = "md_document",
      client = fake_client(api),
      review = function(changes) character(0),
      export_path = file.path(withr::local_tempdir(), "out.docx"),
      timeout = 5
    ),
    "nothing was exported"
  )
  expect_equal(api$n_calls("export"), 0)
})

test_that("the export format follows the export path's extension", {
  skip_without_pandoc()
  api <- knit_api()

  sd_knit(a_paper(), "Tighten it.",
    output_format = "md_document",
    client = fake_client(api),
    review = function(changes) changes$change_id,
    export_path = file.path(withr::local_tempdir(), "out.pdf"),
    timeout = 5
  )

  expect_equal(api$last("export")$body$format, "pdf")
})

test_that("a large-edit continue prompt is answered, not waited out", {
  skip_without_pandoc()
  api <- fake_api(
    "POST /v1/documents/upload" = upload_payload(filename = "paper.md", chunks_count = 6L),
    "POST /v1/chat/async" = list(job_id = "job_1", session_id = "paper-2026", status = "pending"),
    "GET /v1/jobs/job_1" = function(n, req) {
      if (n == 1) job_continue_prompt() else job_completed()
    },
    "POST /v1/chat/paper-2026/continue" = list(status = "resumed")
  )

  expect_message(
    sd_knit(a_paper(), "Restructure every section.",
      output_format = "md_document",
      client = fake_client(api),
      review = sd_review_none,
      timeout = 5
    ),
    "Large edit paused"
  )

  # The default is to stop and keep the applied work rather than spend more.
  expect_false(api$last("continue")$body[["continue"]])
})

test_that("the budget still governs a knit", {
  skip_without_pandoc()
  api <- knit_api()
  client <- fake_client(api, sd_budget(max_operations = 0))

  expect_error(
    sd_knit(a_paper(), "Tighten it.",
      output_format = "md_document", client = client,
      review = sd_review_none, timeout = 5
    ),
    class = "sd_budget_error"
  )
  expect_equal(api$n_calls("chat"), 0)
})

test_that("sd_knit checks its inputs before rendering anything", {
  client <- fake_client(fake_api())

  expect_error(sd_knit("no-such-paper.Rmd", "Edit.", client = client), "No file at")
  skip_without_pandoc()
  expect_error(
    sd_knit(a_paper(), "Edit.", client = client, review = "not a function"),
    "`review` must be a function"
  )
})

test_that("sd_review_console refuses to decide in a script", {
  changes <- sd_changes(
    sd_job(fake_client(fake_api("GET /v1/jobs/job_1" = job_awaiting_objects())), "job_1", "paper-2026")
  )

  skip_if(interactive(), "needs a non-interactive session")
  expect_error(sd_review_console(changes), "will not approve changes in a non-interactive session")
  expect_error(sd_review_console(changes), "review = sd_review_none")
})

test_that("sd_review_none approves nothing at all", {
  expect_null(sd_review_none(NULL))
})
