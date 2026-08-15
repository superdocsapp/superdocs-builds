function buildSessionId(jobId: string, rowNumber: number): string {
  return jobId + "-row-" + rowNumber;
}

function safeFileName(value: string): string {
  return value.replace(/[^a-zA-Z0-9._-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 100) || "Generated_Document";
}

function buildRowIdempotencyKey(spreadsheetId: string, sheetName: string, rowNumber: number, templateId: string): string {
  var source = spreadsheetId + "|" + sheetName + "|" + rowNumber + "|" + templateId;
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, source);
  return digest.map(function (value: number) {
    var hex = (value < 0 ? value + 256 : value).toString(16);
    return hex.length === 1 ? "0" + hex : hex;
  }).join("");
}

function generateRowDocument(row: RosterRow, jobId: string, emailEnabled: boolean, idempotencyKey: string): GenerationResult {
  var route = routeRow(row);
  var baseTemplate = getTemplateBody(route.templateId);
  var rendered = renderTemplate(baseTemplate, row.values);
  var name = String(row.values["Name"] || "Document");
  var fileName = safeFileName(name + "_" + route.templateName);
  try {
    var refined = refineDocumentWithSuperDocs(
      rendered,
      "Review this generated employment document for clarity, consistency, and professional presentation. Do not change factual values such as names, job titles, departments, compensation, dates, addresses, or other roster-supplied values. Preserve the existing document structure and all data-chunk-id attributes.",
      buildSessionId(jobId, row.rowNumber)
    );
    var blob = exportDocumentWithSuperDocs(refined, fileName, "docx");
    var file = saveDocumentToDrive(blob, fileName + ".docx");
    var emailResult = sendDocumentEmail(row, file.getUrl(), route.templateName, emailEnabled);
    return {
      rowNumber: row.rowNumber,
      status: "success",
      idempotencyKey: idempotencyKey,
      templateId: route.templateId,
      documentUrl: file.getUrl(),
      emailed: emailResult.sent,
      emailError: emailResult.error
    };
  } catch (error) {
    return { rowNumber: row.rowNumber, status: "failed", idempotencyKey: idempotencyKey, templateId: route.templateId, error: error instanceof Error ? error.message : String(error) };
  }
}
