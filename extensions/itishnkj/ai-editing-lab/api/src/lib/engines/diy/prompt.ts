import type { EngineEditRequest } from "../types";

export const DIY_PROMPT_VERSION = "diy-selection-context-v2";

const SYSTEM_PROMPT = `You edit an existing professional rich-text document.
Obey the user's instruction exactly.
Preserve meaning unless the instruction says otherwise.
Preserve unrelated content and relevant HTML formatting.
Modify only the requested scope.
Return valid JSON and no markdown fences or commentary.
The JSON shape is: {"replacement_html":"<valid HTML>","explanation":"brief reason"}.
Never include scripts, iframes, event-handler attributes, or external embeds.`;

function textOnly(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<[^>]*>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function outline(documentHtml: string): string {
  return [...documentHtml.matchAll(/<h[1-6][^>]*>([\s\S]*?)<\/h[1-6]>/gi)]
    .map((match) => textOnly(match[1] ?? ''))
    .filter(Boolean)
    .join(' · ')
    .slice(0, 2_000);
}

function nearbyStructure(documentHtml: string, selectionText: string): string {
  const documentText = textOnly(documentHtml);
  const selectedText = textOnly(selectionText);
  const position = selectedText ? documentText.indexOf(selectedText) : -1;
  if (position < 0) return documentText.slice(0, 800);
  return documentText.slice(
    Math.max(0, position - 600),
    Math.min(documentText.length, position + selectedText.length + 600),
  );
}

function selectionContext(request: EngineEditRequest): string {
  const selected = request.selectionHtml || request.selectionText || '';
  if (
    request.scope !== 'selection' ||
    textOnly(request.selectionText ?? selected).length > 12_000
  ) {
    return request.documentHtml;
  }
  return [
    'SELECTED CONTENT:',
    selected,
    '',
    'DOCUMENT OUTLINE:',
    outline(request.documentHtml) || '(no headings)',
    '',
    'NEARBY STRUCTURE (reference only; do not rewrite it):',
    nearbyStructure(request.documentHtml, request.selectionText ?? selected),
  ].join('\n');
}

export function diyContextChars(request: EngineEditRequest): number {
  return selectionContext(request).length;
}

export function buildDiyMessages(request: EngineEditRequest) {
  const target = selectionContext(request);

  return [
    { role: "system" as const, content: SYSTEM_PROMPT },
    {
      role: "user" as const,
      content: [
        `Prompt version: ${DIY_PROMPT_VERSION}`,
        `Scope: ${request.scope}`,
        `Instruction: ${request.instruction}`,
        "",
        request.scope === "selection"
          ? "CONTEXT TO EDIT (selected content is authoritative; nearby structure is reference only):"
          : "CONTENT TO EDIT:",
        target,
        "",
        request.scope === "selection"
          ? "Return replacement HTML for only the selected content."
          : "Return the complete edited document HTML.",
      ].join("\n"),
    },
  ];
}

export function buildRepairMessage(raw: string) {
  return {
    role: "user" as const,
    content: `Your previous response was not valid JSON in the required shape. Return only {"replacement_html":"...","explanation":"..."}.\nPrevious response:\n${raw}`,
  };
}