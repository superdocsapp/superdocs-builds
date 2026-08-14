/**
 * SuperDocsClient.gs  (v3 - async job flow, verified against real docs)
 * -----------------------------------------------------------------------
 * Session-based, async-job API:
 *   sessions/init -> documents/upload-base64 -> chat/async (job_id)
 *   -> poll jobs/{job_id} -> chat/{session_id}/approve (if awaiting_approval)
 *   -> documents/export
 *
 * WHY ASYNC: Gmail/Drive add-on button-click handlers get killed by
 * Google at roughly 30-45 seconds (observed empirically, in production,
 * as an "Exceeded maximum execution time" error - see PROGRESS.md).
 * That is shorter than the general 6-minute Apps Script ceiling.
 * SuperDocs chat calls on real documents can run "from thirty seconds
 * to several minutes" per the task doc, so the synchronous /v1/chat
 * call is the wrong tool here; /v1/chat/async plus polling from a
 * time-driven trigger (see AsyncJobs.gs) is the right one - and so is
 * moving the *uploads* themselves off the click handler too (see
 * AsyncJobs.gs's advanceNotStartedJob and PROGRESS.md).
 * -----------------------------------------------------------------------
 */

const SUPERDOCS_API_BASE = "https://api.superdocs.app/v1";

/**
 * 1a. Start a fresh, empty session.
 * ASSUMPTION (docs didn't show this endpoint's 200 body): response
 * includes a `session_id` field. Logged in PROGRESS.md.
 */
function sdInitSession() {
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({ document_ids: [] }),
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(SUPERDOCS_API_BASE + "/sessions/init", options),
  );
}

/**
 * 1b. Upload the source file (as base64) into a session as the ACTIVE,
 * editable document.
 */
function sdUploadDocument(blob, filename, sessionId) {
  const base64 = Utilities.base64Encode(blob.getBytes());
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({
      filename: filename,
      file_base64: base64,
      session_id: sessionId,
      return_html: false,
    }),
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(SUPERDOCS_API_BASE + "/documents/upload-base64", options),
  );
}

/**
 * 2. Start an ASYNC edit job (does not block waiting for the AI).
 * Returns immediately with { job_id, session_id, status, message }.
 *
 * SPEED VS QUALITY, TRIED AND REVERTED (confirmed by a real test): an
 * earlier version passed model_tier:'core' and thinking_depth:'fast' to
 * cut wait time. A side-by-side comparison against the original
 * document showed this caused real damage: dropped hyperlinks,
 * summarised-away details, and the template's own cover page / header /
 * footer never got applied at all. This task needs deeper reasoning
 * than "fast" mode gives it, so tier/depth are left at the API's
 * default (omitted) rather than re-guessing a "safe" faster setting.
 */
function sdStartAsyncChat(sessionId, instruction) {
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({
      message: instruction,
      session_id: sessionId,
      async_mode: true,
    }),
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(SUPERDOCS_API_BASE + "/chat/async", options),
  );
}

/**
 * Poll a job's current state. Returns the full job object:
 * { job_id, session_id, job_type, status, created_at, updated_at,
 *   progress, result: { response, session_id, document_changes: { ... } } }
 * status is one of: pending | in_progress | awaiting_approval |
 *                    completed | failed | cancelled
 */
function sdGetJobStatus(jobId) {
  const options = {
    method: "get",
    headers: { Authorization: "Bearer " + getApiKey() },
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(
      SUPERDOCS_API_BASE + "/jobs/" + encodeURIComponent(jobId),
      options,
    ),
  );
}

/**
 * 3. Approve (or deny) a batch of proposed changes by change_id.
 * Called when a job's status is 'awaiting_approval'.
 */
function sdApproveChanges(sessionId, changeIds) {
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({
      changes: changeIds.map(function (id) {
        return { change_id: id, approved: true };
      }),
    }),
    muteHttpExceptions: true,
  };
  const url =
    SUPERDOCS_API_BASE + "/chat/" + encodeURIComponent(sessionId) + "/approve";
  return sdHandleResponse(UrlFetchApp.fetch(url, options));
}

/**
 * 4. Export the session's current document as a .docx file.
 *
 * ASSUMPTION (docs cut off before showing the 200 response body): the
 * response is EITHER raw file bytes OR JSON carrying a download URL /
 * base64 payload. Handled defensively; see PROGRESS.md.
 */
function sdExportDocument(sessionId, format, filename) {
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({
      session_id: sessionId,
      format: format || "docx",
      filename: filename,
    }),
    muteHttpExceptions: true,
  };
  const resp = UrlFetchApp.fetch(
    SUPERDOCS_API_BASE + "/documents/export",
    options,
  );
  if (resp.getResponseCode() >= 400) {
    throw new Error(
      "Export failed (" +
        resp.getResponseCode() +
        "): " +
        resp.getContentText(),
    );
  }

  const headers = resp.getHeaders();
  const contentType = headers["Content-Type"] || headers["content-type"] || "";
  if (contentType.indexOf("application/json") !== -1) {
    const json = JSON.parse(resp.getContentText());
    if (json.download_url) {
      return UrlFetchApp.fetch(json.download_url).getBlob();
    }
    if (json.file_base64) {
      return Utilities.newBlob(
        Utilities.base64Decode(json.file_base64),
        MimeType.MICROSOFT_WORD,
        filename,
      );
    }
    throw new Error(
      "Export returned JSON with no recognised download field: " +
        resp.getContentText(),
    );
  }
  return resp.getBlob();
}

/**
 * Upload the house template as a READ-ONLY REFERENCE attachment (distinct
 * from the editable working document - see docs: "attachments are
 * read-only context for the AI to reference, not the editable working
 * document"). Files are processed asynchronously; poll
 * sdGetAttachmentStatus until ready before referencing it in chat.
 */
function sdUploadReferenceAttachment(blob, filename, sessionId) {
  const base64 = Utilities.base64Encode(blob.getBytes());
  const options = {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + getApiKey() },
    payload: JSON.stringify({
      filename: filename,
      file_base64: base64,
      session_id: sessionId,
      return_html: false,
    }),
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(
      SUPERDOCS_API_BASE + "/attachments/upload-base64",
      options,
    ),
  );
}

/**
 * Poll this after sdUploadReferenceAttachment until the attachment is
 * ready to be queried by the AI.
 * CONFIRMED endpoint (checked directly against docs.superdocs.app):
 *   GET /v1/attachments/status/{session_id}
 */
function sdGetAttachmentStatus(sessionId) {
  const options = {
    method: "get",
    headers: { Authorization: "Bearer " + getApiKey() },
    muteHttpExceptions: true,
  };
  const url =
    SUPERDOCS_API_BASE + "/attachments/status/" + encodeURIComponent(sessionId);
  return sdHandleResponse(UrlFetchApp.fetch(url, options));
}

/**
 * List saved templates - handy for finding a HOUSE_TEMPLATE id, and used
 * by the new "pick a template" homepage card (see DriveUI.gs).
 */
function sdListTemplates() {
  const options = {
    method: "get",
    headers: { Authorization: "Bearer " + getApiKey() },
    muteHttpExceptions: true,
  };
  return sdHandleResponse(
    UrlFetchApp.fetch(SUPERDOCS_API_BASE + "/templates", options),
  );
}

function listTemplates() {
  console.log(JSON.stringify(sdListTemplates(), null, 2));
}

// --- Shared plumbing ---------------------------------------------------------

function sdHandleResponse(resp) {
  const code = resp.getResponseCode();
  const text = resp.getContentText();
  if (code >= 400) {
    throw new Error("SuperDocs API error (" + code + "): " + text);
  }
  try {
    return JSON.parse(text);
  } catch (e) {
    throw new Error("SuperDocs API returned non-JSON: " + text);
  }
}

/**
 * Pure function, extracted so it is unit-testable with plain Node/Jest
 * without any Apps Script runtime or live API key (see test/).
 * Handles the "second parse" the task doc warns about, defensively:
 * accepts a JSON string, an already-parsed array, or a missing field.
 */
function parseProposedChanges(raw) {
  if (raw == null) return [];
  if (Array.isArray(raw)) return raw;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.warn("Could not double-parse proposed_changes: " + e);
      return [];
    }
  }
  return [];
}
