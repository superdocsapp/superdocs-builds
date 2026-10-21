const FORMATS = new Set(["PDF", "DOCX", "HTML", "MARKDOWN", "TXT"]);

/**
 * SMS grammar:
 *   EDIT <format> <https-document-url> :: <instruction>
 *   CREATE <format> :: <instruction>
 */
export function parseSms(body) {
  const match = String(body || "").trim().match(/^(EDIT|CREATE)\s+(PDF|DOCX|HTML|MARKDOWN|TXT)(?:\s+(https:\/\/\S+))?\s*::\s*(.+)$/is);
  if (!match) {
    throw new Error("Use: EDIT PDF https://example.com/file.docx :: add a summary");
  }
  const [, action, requestedFormat, reference, instruction] = match;
  if (!FORMATS.has(requestedFormat.toUpperCase())) throw new Error("Unsupported export format.");
  if (action.toUpperCase() === "EDIT" && !reference) {
    throw new Error("EDIT needs an HTTPS document link before ::");
  }
  if (action.toUpperCase() === "CREATE" && reference) {
    throw new Error("CREATE does not take a document link; put the instruction after ::");
  }
  if (instruction.trim().length > 1000) throw new Error("Keep the SMS instruction under 1000 characters.");
  return { action: action.toUpperCase(), format: requestedFormat.toLowerCase(), reference, instruction: instruction.trim() };
}

export const helpText = "Reply: EDIT PDF https://public.example/file.docx :: add a one-paragraph summary";
