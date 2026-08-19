export const TEMPLATES = Object.freeze({
  brief: {
    label: "Decision brief",
    heading: "Decision brief",
    before: "<h2>Context</h2><p>Captured from an AI chat.</p>",
  },
  notes: {
    label: "Research notes",
    heading: "Research notes",
    before: "<h2>Source notes</h2><p>Review the captured material before sharing it.</p>",
  },
  blank: { label: "Blank document", heading: "Untitled", before: "" },
});

export function escapeHtml(value) {
  return String(value).replace(/[&<>\"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  })[character]);
}

export function createDocument({ templateId, title, capturedHtml }) {
  const template = TEMPLATES[templateId] ?? TEMPLATES.blank;
  const safeTitle = escapeHtml(title.trim() || template.heading);
  return `<!doctype html><html><body><h1>${safeTitle}</h1>${template.before}<section data-chat-to-superdocs-capture="true">${capturedHtml}</section></body></html>`;
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

export function createInstruction() {
  return "The captured answer is in the section marked data-chat-to-superdocs-capture. Turn it into a polished document section using the selected template's styling. Preserve headings, nested lists, tables, code blocks, and math exactly. Propose every change for review.";
}

export function newSessionId() {
  return `chat-to-superdocs-${crypto.randomUUID()}`;
}
