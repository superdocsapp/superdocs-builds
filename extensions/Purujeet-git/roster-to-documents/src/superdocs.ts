type SuperDocsChatResponse = {
  document_changes?: { updated_html?: string };
  result?: { document_changes?: { updated_html?: string } };
  [key: string]: unknown;
};

function superDocsRequest(path: string, payload: object): any {
  var apiKey = requireSuperDocsApiKey();
  return UrlFetchApp.fetch(CONFIG.SUPERDOCS_BASE_URL + path, {
    method: "post",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + apiKey },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
}

function refineDocumentWithSuperDocs(html: string, instruction: string, sessionId: string): string {
  var response = superDocsRequest("/v1/chat", {
    message: instruction,
    session_id: sessionId,
    document_html: html,
    approval_mode: "approve_all"
  });
  var code = response.getResponseCode();
  var body = response.getContentText();
  if (code < 200 || code >= 300) throw new Error("SuperDocs chat failed (" + code + "): " + body);
  var parsed = JSON.parse(body) as SuperDocsChatResponse;
  var updated = parsed.document_changes && parsed.document_changes.updated_html;
  if (!updated && parsed.result && parsed.result.document_changes) updated = parsed.result.document_changes.updated_html;
  if (!updated) throw new Error("SuperDocs returned no updated HTML.");
  return updated;
}

function exportDocumentWithSuperDocs(html: string, filename: string, format: "doc" | "docx"): any {
  var response = superDocsRequest("/v1/documents/export", {
    html: html,
    format: format,
    filename: filename
  });
  var code = response.getResponseCode();
  if (code < 200 || code >= 300) throw new Error("SuperDocs export failed (" + code + "): " + response.getContentText());
  return response.getBlob().setName(filename + (format === "docx" ? ".docx" : ".doc"));
}

function getSuperDocsKeyStatus(): { configured: boolean } {
  return { configured: !!getScriptProperty(CONFIG.API_KEY_PROPERTY) };
}
