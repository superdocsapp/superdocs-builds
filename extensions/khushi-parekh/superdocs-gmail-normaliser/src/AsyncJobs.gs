/**
 * AsyncJobs.gs
 * -----------------------------------------------------------------------
 * Gmail/Drive add-on button clicks have a very short execution window
 * (tested in production: "Exceeded maximum execution time" - shorter
 * than Apps Script's general 6-minute ceiling). SuperDocs's own docs say
 * the same thing from the other side: "use chat/async... when you can't
 * afford to block on a synchronous response."
 *
 * IMPORTANT: an earlier version of this project only moved the *edit*
 * step (chat/async + polling) onto this trigger, but still did
 * session-init + document-upload + reference-upload synchronously in
 * the click handler. That still hit "Exceeded maximum execution time"
 * on a real Drive file, because base64-encoding and POSTing two files
 * is itself slow enough to blow the ~30-45s click-handler budget. So
 * this version moves EVERYTHING network-related off the click handler:
 * click handlers in Code.gs/DriveUI.gs now only do local, no-network
 * work (dedupe hash check + queuing) and return immediately. This file
 * does all four stages on a time-driven trigger that polls once a
 * minute:
 *   'not_started'           -> init session, upload doc, upload reference
 *   'waiting_for_reference' -> wait for the reference attachment to be ready
 *   'processing'            -> poll the async edit job, approve when asked
 *   (implicit) completed    -> export, file to Drive, record for dedupe,
 *                               notify the user
 *
 * Pending jobs are tracked in Script Properties as a small JSON array,
 * since a trigger function has no memory of the click that started it.
 * -----------------------------------------------------------------------
 */

const PENDING_JOBS_KEY = "SUPERDOCS_PENDING_JOBS";
const POLL_TRIGGER_FUNCTION = "checkPendingJobs";

/**
 * Called by a click handler right after the local dedupe check passes.
 * Registers the job for the background poller to pick up on the next
 * tick. job.state is 'not_started' to start.
 * job identifies "how to tell the user it's done" via EITHER
 * job.messageId (Gmail - reply on that thread) OR job.notifyEmail
 * (Drive / label-watcher - send an email there instead). Both may be
 * present (label watcher jobs carry both); messageId reply wins.
 */
function trackPendingJob(job) {
  const jobs = loadPendingJobs();
  jobs.push(job);
  savePendingJobs(jobs);
  recordStat("queued");
}

/**
 * The trigger handler - runs every minute (see setupPollingTrigger).
 * Each tracked job is in one of three states:
 *   'not_started'            - nothing uploaded yet; do the uploads now.
 *   'waiting_for_reference'  - the house template attachment is still
 *        processing; once ready, start the actual async chat job.
 *   'processing'             - a chat/async job is running; poll it.
 */
function checkPendingJobs() {
  const jobs = loadPendingJobs();
  if (jobs.length === 0) {
    return;
  }

  const stillPending = [];

  jobs.forEach(function (job) {
    try {
      if (job.state === "not_started") {
        stillPending.push(advanceNotStartedJob(job));
      } else if (job.state === "waiting_for_reference") {
        stillPending.push(advanceWaitingJob(job));
      } else {
        stillPending.push(advanceProcessingJob(job));
      }
    } catch (err) {
      console.error(
        "checkPendingJobs: error advancing job (state=" +
          job.state +
          "): " +
          err,
      );
      stillPending.push(job); // transient failure - keep it, try again next minute
    }
  });

  savePendingJobs(
    stillPending.filter(function (j) {
      return j !== null;
    }),
  );
}

/**
 * Stage 0: the part that used to run synchronously in the click
 * handler. Runs on the polling trigger instead, which gets the normal
 * 6-minute execution ceiling rather than an add-on click handler's much
 * shorter one - this is the actual fix for the "Exceeded maximum
 * execution time" failure (see file header and PROGRESS.md).
 *
 * Re-locates the source file from either a Drive file ID or a Gmail
 * message + original filename (attachments themselves are never
 * carried inside the stored job object, since Apps Script Properties
 * only hold JSON-serialisable data - blobs are re-fetched fresh here).
 */
function advanceNotStartedJob(job) {
  const session = sdInitSession();
  const sessionId = session.session_id;

  let fileBlob, fileName;

  if (job.driveFileId) {
    // Drive-triggered job.
    const file = DriveApp.getFileById(job.driveFileId);
    fileBlob = file.getBlob();
    fileName = job.originalFilename;
  } else if (job.messageId) {
    // Gmail-triggered job (manual click or label watcher) - re-find the
    // same attachment by name, since only the filename (not an index)
    // survives into the stored job.
    const message = GmailApp.getMessageById(job.messageId);
    const match = message
      .getAttachments({ includeInlineImages: false })
      .filter(function (a) {
        return a.getName() === job.originalFilename;
      })[0];
    if (!match) {
      throw new Error(
        "Could not re-find attachment '" +
          job.originalFilename +
          "' on message " +
          job.messageId,
      );
    }
    fileBlob = match.copyBlob();
    fileName = job.originalFilename;
  } else {
    throw new Error(
      "Job has neither driveFileId nor messageId - cannot locate source file.",
    );
  }

  sdUploadDocument(fileBlob, fileName, sessionId);

  const houseTemplateFile = DriveApp.getFileById(HOUSE_TEMPLATE_DRIVE_FILE_ID);
  sdUploadReferenceAttachment(
    houseTemplateFile.getBlob(),
    houseTemplateFile.getName(),
    sessionId,
  );

  return {
    state: "waiting_for_reference",
    sessionId: sessionId,
    messageId: job.messageId, // undefined for pure-Drive jobs - fine
    notifyEmail: job.notifyEmail, // undefined for pure-Gmail jobs - fine
    originalFilename: fileName,
    referenceFilename: houseTemplateFile.getName(),
    contentHash: job.contentHash, // carried through for dedupe recording on success
  };
}

/**
 * Stage 1: wait for the reference attachment to finish processing,
 * then start the real edit job.
 *
 * Uses the CONFIRMED endpoint (GET /v1/attachments/status/{session_id}).
 * Its exact 200-response shape wasn't screenshotted (only the 422 error
 * example was), so this reads defensively: accepts either a bare array
 * or an { attachments: [...] } wrapper, and treats any of a few
 * plausible "done" status strings as ready.
 *
 * SAFETY NET: if the attachment still isn't reported ready after
 * MAX_REFERENCE_WAIT_MS, proceed anyway rather than leaving the job
 * stuck forever - a wrong assumption about the status string shouldn't
 * be able to silently strand every job.
 */
var MAX_REFERENCE_WAIT_MS = 1 * 60 * 1000; // 1 minute

var READY_STATUS_VALUES = [
  "ready",
  "processed",
  "completed",
  "done",
  "success",
  "indexed",
];

function advanceWaitingJob(job) {
  if (!job.referenceUploadedAt) {
    job.referenceUploadedAt = Date.now();
  }

  let isReady = false;
  try {
    const status = sdGetAttachmentStatus(job.sessionId);
    const attachments = Array.isArray(status)
      ? status
      : status.attachments || [];
    const ref = attachments.filter(function (a) {
      return a.filename === job.referenceFilename;
    })[0];
    isReady =
      !!ref &&
      READY_STATUS_VALUES.indexOf(String(ref.status || "").toLowerCase()) !==
        -1;
  } catch (err) {
    console.warn(
      "advanceWaitingJob: status check failed, will rely on the safety-net timeout: " +
        err,
    );
  }

  const elapsed = Date.now() - job.referenceUploadedAt;
  if (!isReady && elapsed < MAX_REFERENCE_WAIT_MS) {
    return job; // keep waiting
  }
  if (!isReady) {
    console.warn(
      "advanceWaitingJob: proceeding after " +
        Math.round(elapsed / 1000) +
        's without a confirmed "ready" status (safety-net timeout).',
    );
  }

  // See SuperDocsClient.gs sdStartAsyncChat comment: this instruction has
  // been through several real-test-driven revisions. Current version
  // fixes (in order discovered): template replacing the active document,
  // the AI inventing "Please fill: ..." placeholder facts, dropped
  // hyperlinks, dropped whole entries, and static (non-field) page
  // numbers. Each rule below maps to one of those real, observed bugs.
  const instruction =
    "The ACTIVE DOCUMENT you are editing already contains a complete, real document with real facts - names, dates, companies, projects, and links. Your job is ONLY to restyle it to match the reference file '" +
    job.referenceFilename +
    "'. You are NOT writing new content and NOT filling in a generic template.\n\n" +
    "CRITICAL RULES - VIOLATING ANY OF THESE IS A FAILURE:\n" +
    "1. USE ONLY REAL DATA FROM THE ACTIVE DOCUMENT: Every fact in your output must come directly from the active document's existing text. NEVER invent, guess, or fabricate any fact, name, company, project, job title, date, location, or skill that is not already present in the active document.\n" +
    "2. NEVER WRITE 'PLEASE FILL' OR ANY PLACEHOLDER TEXT: Do not insert bracketed placeholders, 'Please fill: ...' text, or any instruction-to-self text anywhere in the output. If a field genuinely has no value in the active document, simply omit that field/line entirely.\n" +
    "3. ABSOLUTE CONTENT PRESERVATION: Do NOT drop, omit, summarize, or shorten ANY text, bullet points, sections, or items from the active document. Preserve 100% of the active document's real content, including every sentence and detail exactly as written.\n" +
    "4. NEVER DROP AN ENTRY: Every single entry, item, or project that appears anywhere in the active document must appear somewhere in the output. Before finishing, re-check the active document line by line against your output and confirm nothing was left out and nothing was added that wasn't there.\n" +
    "5. PRESERVE EVERY HYPERLINK, WITH NO EXCEPTIONS: Find every single hyperlink in the source, no matter how short its anchor text is, and carry it into the output as a working, clickable hyperlink on equivalent text.\n" +
    "6. APPLY THE REFERENCE FILE'S STRUCTURE, NOT ITS CONTENT - THIS IS NOT OPTIONAL: Every output MUST include a cover page (title, and a 'Prepared for'/date line, matching the reference file's cover page layout), a header on every content page (with the logo placeholder and a name/company line), and a footer with a page number. This applies even to short documents - do not skip the cover page just because the content is brief. Copy the reference file's heading styles and table styling too. Never copy the reference file's own placeholder text, sample data, or example content into the output - structure only, not content.\n" +
    "7. USE A REAL PAGE NUMBER FIELD: If the reference file's footer shows a page number, insert an actual dynamic page-number field, not static repeated text.";

  const startedJob = sdStartAsyncChat(job.sessionId, instruction);
  return {
    state: "processing",
    jobId: startedJob.job_id,
    sessionId: job.sessionId,
    messageId: job.messageId, // present for Gmail-triggered jobs
    notifyEmail: job.notifyEmail, // present for Drive-triggered jobs
    originalFilename: job.originalFilename,
    referenceFilename: job.referenceFilename,
    contentHash: job.contentHash,
  };
}

/**
 * Stage 2: poll a running chat/async job.
 * Returns the (possibly updated) job, or null if it's finished (success
 * or failure) and should be dropped from the queue.
 */
function advanceProcessingJob(job) {
  const status = sdGetJobStatus(job.jobId);

  if (status.status === "awaiting_approval") {
    const pendingChanges =
      (status.result &&
        status.result.document_changes &&
        status.result.document_changes.pending_changes) ||
      [];
    const changeIds = pendingChanges.map(function (c) {
      return c.change_id;
    });
    if (changeIds.length > 0) {
      sdApproveChanges(job.sessionId, changeIds);
    }
    return job; // resumes processing after approval; poll again next minute
  } else if (status.status === "completed") {
    finishJob(job);
    return null;
  } else if (status.status === "failed" || status.status === "cancelled") {
    notifyFailure(job, "SuperDocs job " + status.status + ".");
    return null;
  } else {
    return job; // pending / in_progress - keep waiting
  }
}

/**
 * Job reached status=completed: export, file to Drive, record for
 * dedupe, then tell the user - a Gmail reply if this came from Gmail
 * (job.messageId), or a direct email if it came from Drive/the label
 * watcher (job.notifyEmail).
 */
function finishJob(job) {
  try {
    const outputName =
      stripExtension(job.originalFilename) + " (normalised).docx";
    const exported = sdExportDocument(job.sessionId, "docx", outputName);
    exported.setName(outputName);

    const folder = DriveApp.getFolderById(DRIVE_FOLDER_ID);
    const savedFile = folder.createFile(exported);

    // Idempotency: remember this content hash -> result so a duplicate
    // attachment (re-clicked, forwarded on another thread, or picked up
    // twice by the label watcher) is recognised next time and skipped
    // instead of spending another SuperDocs operation. See Dedupe.gs.
    if (job.contentHash) {
      try {
        recordProcessed(job.contentHash, {
          driveUrl: savedFile.getUrl(),
          filename: job.originalFilename,
        });
      } catch (dedupeErr) {
        console.warn("Could not record dedupe entry (non-fatal): " + dedupeErr);
      }
    }

    // Automated content-preservation check (see QualityChecks.gs).
    // Wrapped defensively - if this fails for any reason (an
    // unexpected docx internal structure, say), the run still
    // completes and delivers the file; the check is a bonus signal,
    // never a blocker.
    let warning = "";
    try {
      const inputTextLength = extractDocxPlainTextLength(
        DriveApp.getFileById(
          job.driveFileId || HOUSE_TEMPLATE_DRIVE_FILE_ID,
        ).getBlob(),
      );
      // NOTE: for Gmail-triggered jobs the original attachment is no
      // longer available here (only its name was carried in the job);
      // input-length comparison currently only runs for Drive-sourced
      // jobs, where the source file is still addressable by ID. This
      // is a known, logged limitation - see PROGRESS.md - rather than
      // a silently wrong comparison for Gmail jobs.
      const outputTextLength = extractDocxPlainTextLength(exported);
      if (job.driveFileId) {
        warning = buildContentLossWarning(inputTextLength, outputTextLength);
      }
    } catch (checkErr) {
      console.warn("Content-loss check skipped (non-fatal): " + checkErr);
    }

    const bodyText =
      "Your file has been normalised to the house template. " +
      "See the attached file.\n\nDrive copy: " +
      savedFile.getUrl() +
      warning;

    if (job.messageId) {
      const message = GmailApp.getMessageById(job.messageId);
      message.reply(bodyText, {
        attachments: [exported],
        name: "SuperDocs Normaliser",
      });
    } else if (job.notifyEmail) {
      GmailApp.sendEmail(
        job.notifyEmail,
        'SuperDocs Normaliser: "' +
          job.originalFilename +
          '" is ready' +
          (warning ? " (see warning)" : ""),
        bodyText,
        { attachments: [exported], name: "SuperDocs Normaliser" },
      );
    }
    recordStat("completed");
  } catch (err) {
    console.error("finishJob failed for job " + job.jobId + ": " + err);
    notifyFailure(
      job,
      "Finished processing but exporting/filing/notifying failed: " +
        err.message,
    );
  }
}

function notifyFailure(job, reasonText) {
  recordStat("failed");
  try {
    const bodyText =
      'SuperDocs Normaliser could not finish normalising "' +
      job.originalFilename +
      '". ' +
      reasonText;
    if (job.messageId) {
      const message = GmailApp.getMessageById(job.messageId);
      message.reply(bodyText, { name: "SuperDocs Normaliser" });
    } else if (job.notifyEmail) {
      GmailApp.sendEmail(
        job.notifyEmail,
        "SuperDocs Normaliser: normalisation failed",
        bodyText,
      );
    }
  } catch (err) {
    console.error(
      "notifyFailure: could not even send the failure notice: " + err,
    );
  }
}

// --- Storage helpers (Script Properties, small JSON array) -----------------

function loadPendingJobs() {
  const raw =
    PropertiesService.getScriptProperties().getProperty(PENDING_JOBS_KEY);
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Defensive: drop any null/non-object entries so stale or corrupted
    // data (e.g. from an earlier bug or a manual edit) can never crash
    // the trigger again - see the "Cannot read properties of null" bug
    // this fixes, found via a real run.
    return parsed.filter(function (j) {
      return j && typeof j === "object";
    });
  } catch (e) {
    console.warn("Could not parse pending jobs list, resetting it: " + e);
    return [];
  }
}

function savePendingJobs(jobs) {
  PropertiesService.getScriptProperties().setProperty(
    PENDING_JOBS_KEY,
    JSON.stringify(jobs),
  );
}

// --- Trigger management ------------------------------------------------------

/**
 * ONE-TIME SETUP: run this manually from the Apps Script editor (select
 * "setupPollingTrigger" in the function dropdown, click Run). Creates
 * the 1-minute polling trigger exactly once, outside any add-on
 * execution context. (Google enforces a 1-HOUR minimum interval for
 * triggers created from inside an add-on's own click handler, confirmed
 * by a live error - ordinary script triggers created by manually
 * running a function get the normal 1-minute minimum instead, which is
 * why this must be run manually, once, from the editor.)
 */
function setupPollingTrigger() {
  const exists = ScriptApp.getProjectTriggers().some(function (t) {
    return t.getHandlerFunction() === POLL_TRIGGER_FUNCTION;
  });
  if (exists) {
    console.log("Polling trigger already exists - nothing to do.");
    return;
  }
  ScriptApp.newTrigger(POLL_TRIGGER_FUNCTION)
    .timeBased()
    .everyMinutes(1)
    .create();
  console.log(
    "Polling trigger created: checkPendingJobs will now run every minute.",
  );
}
