export function escapeHtml(value) {
  return String(value).replace(/[&<>\"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[character]);
}

export function createDocument({ title, capturedHtml }) {
  const safeTitle = escapeHtml(title.trim() || "AI chat");
  return `<!doctype html><html><body><h1>${safeTitle}</h1><section data-chat-to-superdocs-capture="true">${capturedHtml}</section></body></html>`;
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
  return "The newly captured answer is already present in the final section marked data-chat-to-superdocs-capture. Preserve its headings, nested lists, tables, code blocks, and math exactly. Apply the document's existing styling to that section only. Do not rewrite earlier content. Propose every change for review.";
}

export function createInstruction(template) {
  return `Use my saved SuperDocs template named "${template.name}" (template ID: ${template.id}) as the document's styling source. The captured answer is in the section marked data-chat-to-superdocs-capture. Turn it into a polished document section using that template. Preserve headings, nested lists, tables, code blocks, and math exactly. Propose every change for review.`;
}

export function newSessionId() {
  return `chat-to-superdocs-${crypto.randomUUID()}`;
}
