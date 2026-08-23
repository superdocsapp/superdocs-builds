function getActiveRosterSheet(): any {
  var spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = spreadsheet.getActiveSheet();
  if (!sheet) throw new Error("No active sheet found.");
  return sheet;
}

function getHeaders(sheet: any): string[] {
  var lastColumn = sheet.getLastColumn();
  if (lastColumn === 0) throw new Error("The sheet is empty.");
  return sheet.getRange(1, 1, 1, lastColumn).getDisplayValues()[0].map(function (v: any) { return String(v).trim(); });
}

function readRosterRows(sheet: any, startRow?: number, endRow?: number): RosterRow[] {
  var lastRow = sheet.getLastRow();
  var lastColumn = sheet.getLastColumn();
  if (lastRow < 2 || lastColumn < 1) return [];

  var from = Math.max(2, startRow || 2);
  var to = Math.min(lastRow, endRow || lastRow);
  if (from > to) return [];

  var headers = getHeaders(sheet);
  var values = sheet.getRange(from, 1, to - from + 1, lastColumn).getValues();
  return values.map(function (row: any[], index: number) {
    var data: Record<string, RowValue> = {};
    headers.forEach(function (header, column) {
      if (header) data[header] = row[column] as RowValue;
    });
    return { rowNumber: from + index, values: data };
  });
}

function findHeaderColumn(sheet: any, header: string): number {
  var headers = getHeaders(sheet).map(function (h) { return h.toLowerCase(); });
  var index = headers.indexOf(header.toLowerCase());
  return index === -1 ? -1 : index + 1;
}

function ensureHeader(sheet: any, header: string): number {
  var existing = findHeaderColumn(sheet, header);
  if (existing !== -1) return existing;
  var column = sheet.getLastColumn() + 1;
  sheet.getRange(1, column).setValue(header);
  return column;
}

function writeGenerationResults(sheet: any, results: GenerationResult[]): void {
  if (!results.length) return;
  var linkColumn = ensureHeader(sheet, CONFIG.DEFAULT_OUTPUT_HEADER);
  var statusColumn = ensureHeader(sheet, CONFIG.DEFAULT_STATUS_HEADER);
  var templateColumn = ensureHeader(sheet, CONFIG.DEFAULT_TEMPLATE_HEADER);
  var idempotencyColumn = ensureHeader(sheet, CONFIG.DEFAULT_IDEMPOTENCY_HEADER);

  var startRow = results[0].rowNumber;
  var count = results.length;
  var linkValues = results.map(function (result) { return [result.documentUrl || ""]; });
  var statusValues = results.map(function (result) {
    if (result.status === "failed") return ["Failed: " + (result.error || "Unknown error")];
    if (result.emailError) return ["Generated; email failed: " + result.emailError];
    return [result.emailed ? "Generated + emailed" : "Generated"];
  });
  var templateValues = results.map(function (result) { return [result.templateId || ""]; });
  var idempotencyValues = results.map(function (result) { return [result.idempotencyKey || ""]; });
  sheet.getRange(startRow, linkColumn, count, 1).setValues(linkValues);
  sheet.getRange(startRow, statusColumn, count, 1).setValues(statusValues);
  sheet.getRange(startRow, templateColumn, count, 1).setValues(templateValues);
  sheet.getRange(startRow, idempotencyColumn, count, 1).setValues(idempotencyValues);
}
