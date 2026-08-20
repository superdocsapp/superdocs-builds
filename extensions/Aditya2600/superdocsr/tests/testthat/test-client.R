test_that("a client refuses to exist without a key unless it is offline", {
  withr::local_envvar(SUPERDOCS_API_KEY = "")
  expect_error(sd_client(), "No API key found")

  # A supplied transport is the offline seam, so no key is needed.
  expect_s3_class(sd_client(transport = function(req) req), "sd_client")
})

test_that("the key is never printed in full", {
  client <- sd_client(api_key = "sk_live_abcdefghijklmnop", transport = function(req) req)
  printed <- paste(capture.output(print(client)), collapse = " ")

  expect_false(grepl("abcdefghijklmnop", printed, fixed = TRUE))
  expect_match(printed, "sk_li\\*+nop")
})

test_that("sd_verify_key uses the endpoint that works for sk_ keys", {
  api <- fake_api("GET /v1/sessions" = list())
  expect_true(sd_verify_key(fake_client(api)))
  expect_equal(api$n_calls("GET /v1/sessions"), 1)

  # /v1/users/me is web-app only and would 401 on a valid key; it must not be
  # what we probe with.
  expect_equal(api$n_calls("/v1/users/me"), 0)
})

test_that("requests carry bearer auth and a package user agent", {
  api <- fake_api("GET /v1/sessions" = list())
  sd_verify_key(fake_client(api))
  headers <- httr2::req_get_headers(api$last()$request, redact = "reveal")

  expect_equal(headers$Authorization, "Bearer sk_test_key_not_real")
  expect_match(api$last()$request$options$useragent, "^superdocsr/")
})

test_that("errors name a cause and a fix", {
  api <- fake_api(
    "GET /v1/sessions" = json_response(list(detail = "Invalid API key"), status = 401)
  )
  expect_error(sd_verify_key(fake_client(api)), "Cause: Invalid API key")
  expect_error(sd_verify_key(fake_client(api)), "Fix:.*SUPERDOCS_API_KEY")
})

test_that("errors are classed by status so callers can branch", {
  api <- fake_api("GET /v1/sessions" = json_response(list(detail = "nope"), status = 429))
  expect_error(sd_verify_key(fake_client(api)), class = "sd_http_429")
  expect_error(sd_verify_key(fake_client(api)), class = "sd_api_error")
})

test_that("the three shapes of `detail` all flatten to one readable line", {
  # 422 sends an array of validation records.
  api422 <- fake_api("GET /v1/sessions" = json_response(
    list(detail = list(list(
      type = "string_pattern_mismatch",
      loc = list("body", "session_id"),
      msg = "String should match the expected pattern"
    ))),
    status = 422
  ))
  expect_error(sd_verify_key(fake_client(api422)), "body.session_id: String should match")

  # 413 sends an object.
  api413 <- fake_api("GET /v1/sessions" = json_response(
    list(detail = list(
      error_code = "document_too_large",
      message_user = "This document is 142.3 MB, over the 100 MB export limit."
    )),
    status = 413
  ))
  expect_error(sd_verify_key(fake_client(api413)), "over the 100 MB export limit")

  # The gateway can reject a body with an HTML page rather than JSON.
  apihtml <- fake_api("GET /v1/sessions" = httr2::response(
    status_code = 413,
    headers = list(`Content-Type` = "text/html"),
    body = charToRaw("<html><body>413 Request Entity Too Large</body></html>")
  ))
  expect_error(sd_verify_key(fake_client(apihtml)), "413 Request Entity Too Large")
})

test_that("a transport that does not return a response says so plainly", {
  client <- sd_client(api_key = "sk_x", transport = function(req) "not a response")
  expect_error(sd_verify_key(client), "transport returned a character")
})
