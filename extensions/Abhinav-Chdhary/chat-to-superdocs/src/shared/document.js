export function escapeHtml(value) {
  return String(value).replace(/[&<>\"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[character]);
}

export function createDocument({ capturedHtml }) {
  return `<!doctype html><html><body><section data-chat-to-superdocs-capture="true">${capturedHtml}</section></body></html>`;
}

export function appendCapturedResponse(documentHtml, capturedHtml) {
  const capture = `<section data-chat-to-superdocs-capture="true">${capturedHtml}</section>`;
  return documentHtml.includes("</body>")
    ? documentHtml.replace("</body>", `${capture}</body>`)
    : `${documentHtml}${capture}`;
}

export function conversationKey(url) {
  const parsed = new URL(url);
  return `${parsed.origin}${parsed.pathname.replace(/\/$/, "") || "/"}`;
}

export function appendInstruction() {
  return "The newly captured answer is already present in the final section marked data-chat-to-superdocs-capture. Keep the supplied document HTML exactly unchanged: do not add a title, heading, label, summary, prefix, or any other text. Preserve headings, nested lists, tables, code blocks, and math exactly.";
}

export function createInstruction(template) {
  const styling = template
    ? `If possible without changing document content, apply only the non-content visual styling from my saved SuperDocs template named "${template.name}" (template ID: ${template.id}).`
    : "Do not apply any additional styling beyond the supplied document HTML.";
  return `${styling} Keep the supplied document HTML exactly unchanged: do not add a title, heading, label, summary, prefix, or any other text. Preserve headings, nested lists, tables, code blocks, and math exactly.`;
}

export function newSessionId() {
  return `chat-to-superdocs-${crypto.randomUUID()}`;
}
