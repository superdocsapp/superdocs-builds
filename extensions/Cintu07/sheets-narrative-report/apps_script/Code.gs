/**
 * Sheets narrative report, host side.
 *
 * This layer stays deliberately thin. It reads the selection, calls the service,
 * and renders what comes back. No fact extraction, no formatting, no numeric
 * logic lives here: Apps Script has no test runner worth the name, and the
 * guarantees this build sells have to be testable.
 *
 * The report id is stored per sheet in document properties, which is what makes
 * "run it again after the data changed" resolve to an update of the existing
 * report rather than a brand new one.
 */

var PROP_BASE_URL = 'NARRATIVE_API_BASE';
var PROP_TOKEN = 'NARRATIVE_ADDON_TOKEN';
var MAX_CELLS = 5000;

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Narrative report')
    .addItem('Build report from selection…', 'showSidebar')
    .addSeparator()
    .addItem('Configure service…', 'showSettings')
    .addToUi();
}

function onInstall() {
  onOpen();
}

function showSidebar() {
  var html = HtmlService.createHtmlOutputFromFile('Sidebar')
    .setTitle('Narrative report');
  SpreadsheetApp.getUi().showSidebar(html);
}

function showSettings() {
  var ui = SpreadsheetApp.getUi();
  var props = PropertiesService.getScriptProperties();
  var current = props.getProperty(PROP_BASE_URL) || '';

  var response = ui.prompt(
    'Service URL',
    'Base URL of the narrative report service (e.g. https://reports.example.com).' +
      (current ? '\n\nCurrently: ' + current : ''),
    ui.ButtonSet.OK_CANCEL
  );
  if (response.getSelectedButton() !== ui.Button.OK) return;
  props.setProperty(PROP_BASE_URL, response.getResponseText().trim().replace(/\/+$/, ''));

  var tokenResponse = ui.prompt(
    'Shared token',
    'X-Addon-Token expected by the service. Leave blank if it runs without one.',
    ui.ButtonSet.OK_CANCEL
  );
  if (tokenResponse.getSelectedButton() === ui.Button.OK) {
    props.setProperty(PROP_TOKEN, tokenResponse.getResponseText().trim());
  }
  ui.alert('Saved.');
}

/** Read the current selection into the shape the service expects. */
function readSelection() {
  var sheet = SpreadsheetApp.getActiveSheet();
  var range = sheet.getActiveRange();
  if (!range) {
    throw new Error('Select the range you want reported on, including its header row.');
  }
  var rows = range.getNumRows();
  var cols = range.getNumColumns();
  if (rows < 2 || cols < 2) {
    throw new Error(
      'Select at least two rows and two columns: a header row of periods and a column of line items.'
    );
  }
  if (rows * cols > MAX_CELLS) {
    throw new Error(
      'That selection is ' + rows * cols + ' cells. Narrow it to ' + MAX_CELLS + ' or fewer.'
    );
  }

  // getDisplayValues keeps the sheet's own formatting ($, %, parentheses), which
  // is what the parser reads units from. getValues would throw that away.
  return {
    values: range.getDisplayValues(),
    sheet: sheet.getName(),
    a1: range.getA1Notation(),
    reportId: documentProperty_(reportKey_(sheet, range))
  };
}

function reportKey_(sheet, range) {
  return 'report:' + sheet.getSheetId() + ':' + range.getA1Notation();
}

function documentProperty_(key) {
  return PropertiesService.getDocumentProperties().getProperty(key) || null;
}

/** Ask the service what the report would say. Nothing is written yet. */
function proposeReport() {
  var selection = readSelection();
  var payload = {
    values: selection.values,
    sheet: selection.sheet,
    a1: selection.a1,
    title: SpreadsheetApp.getActiveSpreadsheet().getName() + ', ' + selection.sheet
  };
  if (selection.reportId) payload.report_id = selection.reportId;

  var result = call_('POST', '/reports/propose', payload);
  result._selection = { sheet: selection.sheet, a1: selection.a1 };
  return result;
}

/** Apply the reviewer's decisions and fetch the export. */
function commitReport(reportId, decisions, format) {
  var result = call_('POST', '/reports/' + encodeURIComponent(reportId) + '/commit', {
    decisions: decisions,
    format: format || 'docx'
  });

  // Remember the id against this exact range so the next run is an update.
  var sheet = SpreadsheetApp.getActiveSheet();
  var range = sheet.getActiveRange();
  if (range) {
    PropertiesService.getDocumentProperties().setProperty(reportKey_(sheet, range), reportId);
  }
  return result;
}

/** Pull the exported file into Drive and hand back a link. */
function saveExportToDrive(reportId, format) {
  var config = config_();
  var url =
    config.base + '/reports/' + encodeURIComponent(reportId) + '/download?format=' + format;
  var response = UrlFetchApp.fetch(url, {
    method: 'get',
    headers: config.headers,
    muteHttpExceptions: true
  });
  if (response.getResponseCode() !== 200) {
    throw new Error('Download failed (' + response.getResponseCode() + ').');
  }
  var blob = response.getBlob().setName(reportId + '.' + format);
  var file = DriveApp.createFile(blob);
  return { url: file.getUrl(), name: file.getName() };
}

function config_() {
  var props = PropertiesService.getScriptProperties();
  var base = props.getProperty(PROP_BASE_URL);
  if (!base) {
    throw new Error('No service URL configured. Use “Narrative report → Configure service…” first.');
  }
  var headers = { 'Content-Type': 'application/json' };
  var token = props.getProperty(PROP_TOKEN);
  if (token) headers['X-Addon-Token'] = token;
  return { base: base, headers: headers };
}

/**
 * One HTTP helper, so error handling is in one place.
 *
 * Failures are surfaced with the service's own cause-and-fix message rather
 * than a status code, because the person reading it is a finance analyst in a
 * sidebar, not an engineer with the logs open.
 */
function call_(method, path, body) {
  var config = config_();
  var response = UrlFetchApp.fetch(config.base + path, {
    method: method,
    headers: config.headers,
    payload: JSON.stringify(body),
    muteHttpExceptions: true,
    followRedirects: true
  });

  var code = response.getResponseCode();
  var text = response.getContentText();

  if (code >= 200 && code < 300) {
    return JSON.parse(text);
  }

  var detail;
  try {
    detail = JSON.parse(text).detail;
  } catch (e) {
    detail = text;
  }
  if (detail && typeof detail === 'object') {
    throw new Error(
      (detail.error || 'Request failed') +
        (detail.cause ? ', ' + detail.cause : '') +
        (detail.fix ? '\n\nTry: ' + detail.fix : '')
    );
  }
  if (code === 429) {
    throw new Error('The SuperDocs account is out of operations this month.');
  }
  throw new Error('Request failed (' + code + '): ' + String(detail).slice(0, 300));
}
