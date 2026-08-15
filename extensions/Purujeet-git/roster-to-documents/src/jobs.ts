function getJobKey(jobId: string): string { return CONFIG.JOB_PROPERTY_PREFIX + jobId; }

function saveJob(job: JobState): void {
  job.updatedAt = Date.now();
  var props = PropertiesService.getScriptProperties();
  props.setProperty(getJobKey(job.jobId), JSON.stringify(job));
  props.setProperty("ROSTER_ACTIVE_JOB_ID", job.jobId);
}

function loadJob(jobId: string): JobState {
  var raw = PropertiesService.getScriptProperties().getProperty(getJobKey(jobId));
  if (!raw) throw new Error("Job not found: " + jobId);
  var job = JSON.parse(raw) as JobState;
  // Backward-compatible defaults for jobs created before these fields existed.
  if (typeof job.emailEnabled !== "boolean") job.emailEnabled = false;
  if (!job.updatedAt) job.updatedAt = Date.now();
  if (!job.currentAction) job.currentAction = job.status === "running" ? "Queued" : "";
  return job;
}

function createJob(sheet: any): JobState {
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) throw new Error("No roster rows found.");
  var jobId = Utilities.getUuid();
  var outputColumn = ensureHeader(sheet, CONFIG.DEFAULT_OUTPUT_HEADER);
  var job: JobState = {
    jobId: jobId,
    spreadsheetId: SpreadsheetApp.getActiveSpreadsheet().getId(),
    sheetName: sheet.getName(),
    outputColumn: outputColumn,
    status: "preview",
    startRow: 2,
    nextRow: 2,
    endRow: Math.min(lastRow, CONFIG.MAX_ROWS_PER_JOB + 1),
    totalRows: Math.min(lastRow - 1, CONFIG.MAX_ROWS_PER_JOB),
    completedRows: 0,
    emailEnabled: isEmailEnabledByDefault(),
    updatedAt: Date.now(),
    results: []
  };
  saveJob(job);
  return job;
}

function previewFirstThree(): { jobId: string; results: GenerationResult[] } {
  var lock = LockService.getScriptLock();
  lock.tryLock(10000);
  try {
    var sheet = getActiveRosterSheet();
    var configuredTemplate = getScriptProperty(CONFIG.TEMPLATE_PROPERTY).trim().toLowerCase();
    if (!configuredTemplate || configuredTemplate === "auto" || !getTemplateDefinitions().some(function (definition) { return definition.id === configuredTemplate; })) {
      prepareDynamicTemplatesForSheet(sheet);
    }
    var job = createJob(sheet);
    var rows = readRosterRows(sheet, 2, Math.min(4, sheet.getLastRow()));
    var previewResults = rows.map(function (row) {
      var route = routeRow(row);
      try {
        var template = getTemplateBody(route.templateId);
        var rendered = renderTemplate(template, row.values);
        return {
          rowNumber: row.rowNumber,
          status: "success" as "success",
          templateId: route.templateId,
          documentUrl: "",
          error: "Preview passed — template " + route.templateId + "; rendered " + rendered.length + " HTML characters."
        };
      } catch (error) {
        return {
          rowNumber: row.rowNumber,
          status: "failed" as "failed",
          templateId: route.templateId,
          documentUrl: "",
          error: error instanceof Error ? error.message : String(error)
        };
      }
    });
    return { jobId: job.jobId, results: previewResults };
  } finally {
    lock.releaseLock();
  }
}

function startFullGeneration(jobId: string, emailEnabled?: boolean): void {
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var job = loadJob(jobId);
    if (typeof emailEnabled === "boolean") job.emailEnabled = emailEnabled;
    if (job.status === "completed") return;
    job.status = "running";
    job.currentAction = "Queued — waiting to process the next row";
    saveJob(job);
  } finally {
    lock.releaseLock();
  }
  scheduleNextBatch();
}

function clearBatchTriggers(): void {
  ScriptApp.getProjectTriggers().forEach(function (trigger: GoogleAppsScript.Script.Trigger) {
    if (trigger.getHandlerFunction() === "resumeGenerationTrigger") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function cancelJob(jobId: string): JobState {
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var job = loadJob(jobId);
    job.status = "cancelled";
    job.currentAction = "Cancelled by user";
    saveJob(job);
    clearBatchTriggers();
    PropertiesService.getScriptProperties().deleteProperty("ROSTER_ACTIVE_JOB_ID");
    return job;
  } finally {
    lock.releaseLock();
  }
}

function scheduleNextBatch(): void {
  // A previous run may have left continuation triggers behind. Keep exactly
  // one trigger for this handler so repeated starts cannot exhaust the Apps
  // Script trigger quota.
  clearBatchTriggers();
  ScriptApp.newTrigger("resumeGenerationTrigger").timeBased().after(1000).create();
}

function runJobBatch(jobId: string): void {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(5000)) return;
  try {
    var job = loadJob(jobId);
    if (job.status !== "running") return;
    var sheet = SpreadsheetApp.openById(job.spreadsheetId).getSheetByName(job.sheetName);
    if (!sheet) throw new Error("Sheet not found: " + job.sheetName);

    var batchEnd = Math.min(job.endRow, job.nextRow + CONFIG.DEFAULT_BATCH_SIZE - 1);
    var rows = readRosterRows(sheet, job.nextRow, batchEnd);
    rows.forEach(function (row) {
      job.currentRow = row.rowNumber;
      job.currentAction = "Creating document for row " + row.rowNumber + "…";
      saveJob(job);
      var route = routeRow(row);
      var idempotencyKey = buildRowIdempotencyKey(job.spreadsheetId, job.sheetName, row.rowNumber, route.templateId);
      var existingKey = String(row.values[CONFIG.DEFAULT_IDEMPOTENCY_HEADER] || "");
      var existingLink = String(row.values[CONFIG.DEFAULT_OUTPUT_HEADER] || "");
      var alreadyCommitted = existingKey === idempotencyKey && existingLink.trim() !== "";
      var result = alreadyCommitted
        ? { rowNumber: row.rowNumber, status: "success" as "success", idempotencyKey: idempotencyKey, templateId: route.templateId, documentUrl: existingLink }
        : generateRowDocument(row, job.jobId, job.emailEnabled, idempotencyKey);
      // Commit each row immediately. If Apps Script or the browser stops,
      // the saved cursor still points at the first uncommitted row.
      if (!alreadyCommitted) writeGenerationResults(sheet, [result]);
      job.results = job.results.concat([result]);
      job.completedRows += 1;
      job.nextRow = row.rowNumber + 1;
      job.lastCompletedRow = row.rowNumber;
      job.currentAction = result.status === "success"
        ? "Row " + row.rowNumber + " completed — link inserted"
        : "Row " + row.rowNumber + " failed";
      saveJob(job);
    });

    if (job.nextRow > job.endRow) {
      job.status = "completed";
      saveJob(job);
      clearBatchTriggers();
      return;
    }

    job.currentAction = "Waiting to process row " + job.nextRow + "…";
    saveJob(job);
    scheduleNextBatch();
  } finally {
    lock.releaseLock();
  }
}

function resumeGenerationTrigger(): void {
  var jobId = PropertiesService.getScriptProperties().getProperty("ROSTER_ACTIVE_JOB_ID");
  if (!jobId) return;
  var job = loadJob(jobId);
  if (job.status === "running") runJobBatch(jobId);
}

function getJobStatus(jobId: string): JobState {
  return loadJob(jobId);
}

function getActiveJobForCurrentSheet(): JobState | null {
  var jobId = PropertiesService.getScriptProperties().getProperty("ROSTER_ACTIVE_JOB_ID");
  if (!jobId) return null;
  try {
    var job = loadJob(jobId);
    var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = spreadsheet.getActiveSheet();
    if (job.spreadsheetId !== spreadsheet.getId() || job.sheetName !== sheet.getName()) return null;
    return job;
  } catch (_error) {
    return null;
  }
}
