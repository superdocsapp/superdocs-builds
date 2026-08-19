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

export function appendInstruction() {
  return "Append the captured answer at the end of this document. Preserve its headings, nested lists, tables, code blocks, and math exactly. Do not rewrite existing content. Propose every insertion for review.";
}

export function createInstruction() {
  return "Format the captured answer as the final section of this document. Preserve its headings, nested lists, tables, code blocks, and math exactly. Propose every change for review.";
}

export function newSessionId() {
  return `chat-to-superdocs-${crypto.randomUUID()}`;
}
