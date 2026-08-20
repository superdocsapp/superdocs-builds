# A fake SuperDocs API. Every test in this suite runs against it, so the suite
# needs no API key, spends no operations, and touches no network.
#
# Routes are named by a regular expression matched against "METHOD /path".
# A route's value is either a literal httr2 response, a list (encoded as a 200
# JSON body), or a function(n, req) where `n` is how many times that route has
# been called -- which is how a job is made to report in_progress before it
# reports completed.

json_response <- function(body = list(), status = 200L, headers = list()) {
  headers <- utils::modifyList(list(`Content-Type` = "application/json"), headers)
  httr2::response(
    status_code = status,
    headers = headers,
    body = charToRaw(jsonlite::toJSON(body, auto_unbox = TRUE, null = "null"))
  )
}

raw_response <- function(bytes, status = 200L, headers = list()) {
  httr2::response(status_code = status, headers = headers, body = bytes)
}

fake_api <- function(...) {
  routes <- list(...)
  state <- new.env(parent = emptyenv())
  state$log <- list()
  state$counts <- list()

  transport <- function(req) {
    method <- if (is.null(req$method)) "GET" else req$method
    path <- httr2::url_parse(req$url)$path
    key <- paste(method, path)

    n <- (state$counts[[key]] %||% 0L) + 1L
    state$counts[[key]] <- n
    state$log[[length(state$log) + 1L]] <- list(
      key = key, method = method, path = path,
      request = req, body = req$body$data
    )

    hit <- Find(function(pattern) grepl(pattern, key), names(routes))
    if (is.null(hit)) {
      stop("fake_api: no route matches '", key, "'", call. = FALSE)
    }
    handler <- routes[[hit]]
    resp <- if (is.function(handler)) handler(n, req) else handler
    if (inherits(resp, "httr2_response")) resp else json_response(resp)
  }

  list(
    transport = transport,
    calls = function() state$log,
    n_calls = function(pattern = NULL) {
      if (is.null(pattern)) {
        return(length(state$log))
      }
      sum(vapply(state$log, function(call) grepl(pattern, call$key), logical(1)))
    },
    last = function(pattern = NULL) {
      calls <- state$log
      if (!is.null(pattern)) {
        calls <- Filter(function(call) grepl(pattern, call$key), calls)
      }
      if (length(calls) == 0L) NULL else calls[[length(calls)]]
    }
  )
}

# A client wired to a fake API, with a budget generous enough not to be the
# thing under test unless a test says so.
fake_client <- function(api, budget = sd_budget(max_operations = 100)) {
  sd_client(
    api_key = "sk_test_key_not_real",
    base_url = "https://api.superdocs.test",
    budget = budget,
    transport = api$transport,
    max_tries = 1
  )
}

# A file on disk with an accepted extension. The bytes do not matter: the fake
# API never parses them, and sd_upload() streams the file rather than reading
# it.
test_docx <- function(env = parent.frame()) {
  path <- withr::local_tempfile(fileext = ".docx", .local_envir = env)
  writeBin(charToRaw("PK not really a docx"), path)
  path
}

# --- fixtures, shaped exactly like the documented payloads --------------------

upload_payload <- function(session_id = "paper-2026",
                           filename = "manuscript.docx",
                           chunks_count = 12L) {
  list(
    html = "<div data-chunk-id=\"c1\"><h1>Title</h1></div>",
    session_id = session_id,
    filename = filename,
    chunks_count = chunks_count,
    version_id = "v_1",
    page_setup = list(
      width_in = 8.27, height_in = 11.69,
      margin_in = list(top = 1, right = 1, bottom = 1, left = 1),
      orientation = "portrait", source = "docx"
    )
  )
}

a_change <- function(id = "ch_1", operation = "edit") {
  list(
    change_id = id,
    operation = operation,
    chunk_id = "550e8400-e29b-41d4-a716-446655440000",
    old_html = "<p>The effect was very significant.</p>",
    new_html = "<p>The effect was significant (p = 0.03).</p>",
    ai_explanation = "Replaced an intensifier with the reported statistic",
    insert_after_chunk_id = NULL,
    document_id = "doc_1"
  )
}

# A job paused on a HITL review, with the changes delivered as plain objects.
job_awaiting_objects <- function(changes = list(a_change())) {
  list(
    job_id = "job_1", session_id = "paper-2026", job_type = "chat",
    status = "awaiting_approval", progress = 50,
    created_at = "2026-08-10T10:00:00Z", updated_at = "2026-08-10T10:00:30Z",
    metadata = list(pending_changes = changes)
  )
}

# The same job, but with the batch delivered the way the API actually delivers
# it: `content` is a JSON-encoded string that has to be parsed a second time.
job_awaiting_batch_string <- function(changes = list(a_change("ch_1"), a_change("ch_2", "create")),
                                      batch_total = 2L) {
  content <- jsonlite::toJSON(
    list(
      type = "batch_approval",
      batch_id = "ch_1",
      batch_total = batch_total,
      changes = changes
    ),
    auto_unbox = TRUE, null = "null"
  )
  list(
    job_id = "job_1", session_id = "paper-2026", job_type = "chat",
    status = "awaiting_approval", progress = 50,
    created_at = "2026-08-10T10:00:00Z", updated_at = "2026-08-10T10:00:30Z",
    metadata = list(
      intermediate_responses = list(
        list(type = "intermediate", content = "Reading section 3...", sequence = 1),
        list(type = "proposed_change_batch", content = unclass(content), sequence = 2)
      )
    )
  )
}

job_completed <- function(job_id = "job_1") {
  list(
    job_id = job_id, session_id = "paper-2026", job_type = "chat",
    status = "completed", progress = 100,
    created_at = "2026-08-10T10:00:00Z", updated_at = "2026-08-10T10:02:00Z",
    result = list(
      response = "Done.",
      session_id = "paper-2026",
      document_changes = list(
        updated_html = "<div data-chunk-id=\"c1\">edited</div>",
        version_id = "v_2",
        changes_summary = "Document updated by AI"
      ),
      usage = list(
        monthly_used = 44, monthly_limit = 500, monthly_remaining = 456,
        was_billable = TRUE, subscription_tier = "free"
      )
    )
  )
}

job_in_progress <- function() {
  list(
    job_id = "job_1", session_id = "paper-2026", job_type = "chat",
    status = "in_progress", progress = 20,
    created_at = "2026-08-10T10:00:00Z", updated_at = "2026-08-10T10:00:10Z"
  )
}

job_continue_prompt <- function() {
  list(
    job_id = "job_1", session_id = "paper-2026", job_type = "chat",
    status = "awaiting_approval", progress = 60,
    created_at = "2026-08-10T10:00:00Z", updated_at = "2026-08-10T10:01:00Z",
    metadata = list(
      awaiting_kind = "continue_prompt",
      continue_prompt = list(
        message = "I've updated 500 of 864 sections so far. 364 remain. Want me to continue?",
        done = 500, total = 864, remaining = 364
      )
    )
  )
}
