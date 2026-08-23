function onOpen(): void {
  SpreadsheetApp.getUi().createMenu("Roster to Documents")
    .addItem("Open sidebar", "showSidebar")
    .addItem("Settings", "showSettings")
    .addItem("Preview first 3 rows", "previewAndShow")
    .addItem("Generate / refresh 10 AI templates", "generateTemplatesAndShow")
    .addToUi();
}

function showSidebar(): void {
  var html = HtmlService.createHtmlOutputFromFile("sidebar/index")
    .setTitle("Roster to Documents");
  SpreadsheetApp.getUi().showSidebar(html);
}

function showSettings(): void {
  var html = HtmlService.createHtmlOutputFromFile("settings/index")
    .setWidth(420)
    .setHeight(300);
  SpreadsheetApp.getUi().showModalDialog(html, "Roster to Documents settings");
}

function getSettingsState(): object {
  return { superDocsConfigured: getSuperDocsKeyStatus().configured };
}

function saveSuperDocsApiKey(apiKey: string): object {
  var key = String(apiKey || "").trim();
  if (!key) {
    throw new Error("Enter a SuperDocs API key.");
  }
  PropertiesService.getScriptProperties().setProperty(CONFIG.API_KEY_PROPERTY, key);
  return { superDocsConfigured: true };
}

function getInitialState(): object {
  var sheet = getActiveRosterSheet();
  var headers = getHeaders(sheet);
  return {
    sheetName: sheet.getName(),
    headers: headers,
    totalRows: Math.max(0, sheet.getLastRow() - 1),
    superDocsConfigured: getSuperDocsKeyStatus().configured,
    defaultEmailEnabled: isEmailEnabledByDefault(),
    activeJob: getActiveJobForCurrentSheet()
  };
}

function previewAndShow(): void {
  var ui = SpreadsheetApp.getUi();
  try {
    var preview = previewFirstThree();
    ui.alert("Preview ready", preview.results.map(function (result) {
      return "Row " + result.rowNumber + " → " + (result.templateId || "general") + " — " + (result.error || "OK");
    }).join("\n"), ui.ButtonSet.OK);
  } catch (error) {
    ui.alert("Preview failed", error instanceof Error ? error.message : String(error), ui.ButtonSet.OK);
  }
}

function runPreview(): object {
  return previewFirstThree();
}

function prepareTemplatesForCurrentSheet(): object {
  return prepareDynamicTemplatesForSheet(getActiveRosterSheet());
}

function startGeneration(jobId: string, emailEnabled: boolean): object {
  startFullGeneration(jobId, emailEnabled);
  return getJobStatus(jobId);
}

function resumeGeneration(jobId: string): object {
  startFullGeneration(jobId);
  return getJobStatus(jobId);
}

function cancelGeneration(jobId: string): JobState {
  return cancelJob(jobId);
}

function getStatus(jobId: string): JobState {
  return getJobStatus(jobId);
}

// The sidebar uses this endpoint to advance one row and immediately receive
// the updated progress. A time-based trigger remains as a fallback if the
// sidebar is closed.
function advanceGeneration(jobId: string): JobState {
  runJobBatch(jobId);
  return getJobStatus(jobId);
}

function generateTemplatesAndShow(): void {
  var ui = SpreadsheetApp.getUi();
  try {
    var result = generateAllTemplatesWithSuperDocs();
    ui.alert("Templates generated", "Generated " + result.generated.length + " templates in Drive folder: " + result.folderId, ui.ButtonSet.OK);
  } catch (error) {
    ui.alert("Template generation failed", error instanceof Error ? error.message : String(error), ui.ButtonSet.OK);
  }
}
