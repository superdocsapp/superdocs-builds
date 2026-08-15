function normalizeEmail(value: RowValue): string {
  return String(value == null ? "" : value).trim();
}

function sendDocumentEmail(row: RosterRow, documentUrl: string, templateName: string, enabled: boolean): { sent: boolean; error?: string } {
  if (!enabled) {
    return { sent: false };
  }
  var email = normalizeEmail(row.values["Email"] || row.values["email"] || "");
  if (!email) return { sent: false, error: "Email address missing" };
  var name = String(row.values["Name"] || "there");
  try {
    GmailApp.sendEmail(email, "Your " + templateName + " document", "Hello " + name + ",\n\nYour personalized document is ready:\n" + documentUrl + "\n\nRegards,\nHR / Administration");
    return { sent: true };
  } catch (error) {
    return { sent: false, error: error instanceof Error ? error.message : String(error) };
  }
}
