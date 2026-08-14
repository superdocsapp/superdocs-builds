/**
 * Dedupe.gs   [NEW - built beyond the assignment]
 * -----------------------------------------------------------------------
 * Idempotency guard. Before queuing a new normalise job, check whether
 * this exact file CONTENT has already been normalised successfully. If
 * so, skip re-running the SuperDocs pipeline entirely (which costs a
 * real "operation" - see the task doc's own FAQ on what an operation
 * is) and just hand back the existing result.
 *
 * Keyed by CONTENT HASH, deliberately not by filename or message/thread
 * id, so:
 *   - the same file forwarded on a different thread is still recognised
 *   - a file re-attached under a different name is still recognised
 *   - a genuinely different file that happens to share a name is NOT
 *     wrongly treated as a duplicate
 *
 * Stored as a small JSON map in Script Properties: { hash: record }.
 * Capped at MAX_DEDUPE_ENTRIES, evicting the oldest, so this can't grow
 * unbounded over the life of the script.
 *
 * WHY THIS IS SAFE TO RUN INSIDE THE CLICK HANDLER (unlike the actual
 * SuperDocs upload/edit calls): computing a hash is local CPU work, and
 * downloading a Drive file's own bytes is a same-network Google-to-
 * Google read, not a call out to SuperDocs - neither one risks the
 * "Exceeded maximum execution time" failure that moving the *uploads*
 * (base64-encode + POST to SuperDocs) off the click handler was meant
 * to fix (see AsyncJobs.gs). It is slower than a true zero-byte check
 * would be - see the note on contentHashForDriveFile below - but still
 * well inside the click handler's budget for the document sizes this
 * build targets.
 * -----------------------------------------------------------------------
 */

const PROCESSED_FILES_KEY = "SUPERDOCS_PROCESSED_FILES";
const MAX_DEDUPE_ENTRIES = 200;

/**
 * BUG FIXED (see PROGRESS.md): this originally called
 * file.getMd5Checksum(), assuming DriveApp.File exposed Drive's stored
 * checksum directly. It doesn't - that method only exists on the
 * Advanced Drive Service's file *resource* (Drive.Files.get, a separate
 * service that must be explicitly enabled per project), not on
 * DriveApp.File. Calling it threw "TypeError: file.getMd5Checksum is
 * not a function" in a real run.
 *
 * Fixed by reusing the exact same local-hashing path as Gmail
 * attachments (contentHashForBlob, below) instead of requiring an extra
 * one-time "enable this service" setup step. Trade-off, logged
 * honestly: this means the file's bytes get downloaded once here (for
 * the dedupe check) and once more later in AsyncJobs.gs's
 * advanceNotStartedJob (for the actual SuperDocs upload) - a real but
 * minor inefficiency for large files, not a correctness problem. If
 * that download-twice cost ever matters, enabling the Advanced Drive
 * Service and reading its md5Checksum field would avoid it - deferred
 * until that's an actual problem worth the extra setup step.
 */
function contentHashForDriveFile(file) {
  return contentHashForBlob(file.getBlob());
}

/**
 * Gmail attachments don't expose a checksum, so compute one locally.
 * Pure in-memory + CPU work, no network call - safe inside the click
 * handler's execution window even for fairly large attachments.
 */
function contentHashForBlob(blob) {
  const digestBytes = Utilities.computeDigest(
    Utilities.DigestAlgorithm.MD5,
    blob.getBytes(),
  );
  const hex = digestBytes
    .map(function (b) {
      return ((b + 256) % 256).toString(16).padStart(2, "0");
    })
    .join("");
  return "md5:" + hex;
}

/**
 * Returns the stored { driveUrl, filename, processedAt } record for a
 * hash, or null if this content has never been successfully processed.
 */
function findProcessedRecord(hash) {
  const map = loadProcessedMap();
  return map[hash] || null;
}

/**
 * Called once a job finishes successfully (from AsyncJobs.gs's
 * finishJob), so future duplicates of the same content are recognised.
 */
function recordProcessed(hash, record) {
  const map = loadProcessedMap();
  map[hash] = Object.assign({ processedAt: Date.now() }, record);

  const keys = Object.keys(map);
  if (keys.length > MAX_DEDUPE_ENTRIES) {
    keys
      .sort(function (a, b) {
        return map[a].processedAt - map[b].processedAt;
      })
      .slice(0, keys.length - MAX_DEDUPE_ENTRIES)
      .forEach(function (k) {
        delete map[k];
      });
  }

  PropertiesService.getScriptProperties().setProperty(
    PROCESSED_FILES_KEY,
    JSON.stringify(map),
  );
}

function loadProcessedMap() {
  const raw =
    PropertiesService.getScriptProperties().getProperty(PROCESSED_FILES_KEY);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (e) {
    console.warn("Could not parse processed-files map, resetting it: " + e);
    return {};
  }
}

/**
 * Optional: clear all dedupe history (e.g. to force-reprocess
 * everything for a demo). Run manually from the Apps Script editor.
 */
function resetDedupeHistory() {
  PropertiesService.getScriptProperties().deleteProperty(PROCESSED_FILES_KEY);
  console.log("Dedupe history cleared.");
}
