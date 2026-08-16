import type { NotebookCell, NotebookDocument, SourceRef } from "./types.js";
import { createSourceRef } from "./evidence.js";

export interface PromptInjectionFinding {
  source: SourceRef;
  location: "source" | "output";
  excerpt: string;
  signal: string;
}

const PROMPT_INJECTION_SIGNALS: Array<[RegExp, string]> = [
  [/ignore\s+(?:all\s+)?previous\s+instructions?/i, "instruction override"],
  [/(?:system|developer)\s+(?:message|prompt)\s*:/i, "role impersonation"],
  [/(?:reveal|print|show|leak)\s+(?:the\s+)?(?:api\s*key|secret|credentials?)/i, "secret exfiltration"],
  [/(?:execute|run)\s+(?:this\s+)?(?:command|code|shell)/i, "execution request"],
  [/(?:do\s+not|never)\s+(?:tell|show|report)\s+(?:the\s+)?user/i, "concealment request"],
];

export function scanNotebookForPromptInjection(notebook: NotebookDocument): PromptInjectionFinding[] {
  const findings: PromptInjectionFinding[] = [];
  for (const cell of notebook.cells) {
    scanText(findings, notebook, cell, "source", cell.source);
    for (const output of cell.outputs) {
      const text = output.text || output.html || normalize(output.data?.["text/plain"]);
      if (text) scanText(findings, notebook, cell, "output", text);
    }
  }
  return findings;
}

function scanText(
  findings: PromptInjectionFinding[],
  notebook: NotebookDocument,
  cell: NotebookCell,
  location: "source" | "output",
  text: string,
): void {
  for (const [pattern, signal] of PROMPT_INJECTION_SIGNALS) {
    const match = text.match(pattern);
    if (!match || match.index === undefined) continue;
    const start = Math.max(0, match.index - 40);
    const end = Math.min(text.length, match.index + match[0].length + 80);
    findings.push({
      source: createSourceRef(notebook, cell),
      location,
      excerpt: text.slice(start, end),
      signal,
    });
  }
}

function normalize(value: unknown): string | undefined {
  if (Array.isArray(value)) return value.join("");
  return typeof value === "string" ? value : undefined;
}
