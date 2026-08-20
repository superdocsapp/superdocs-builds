export type LineAutofix = {
  kind: "replace-line";
  line: number;
  before: string;
  after: string;
};

export type ApplyAutofixRefusal =
  | "empty-file"
  | "line-out-of-range"
  | "content-drift"
  | "no-op";

export type ApplyAutofixResult =
  | {
      ok: true;
      content: string;
      changedLines: number[];
    }
  | {
      ok: false;
      refusal: ApplyAutofixRefusal;
      detail: string;
    };

type SourceLine = {
  text: string;
  terminator: string;
};

/**
 * Applies one anchored single-line replacement.
 *
 * The autofix carries the line text it expects to find. If the file has moved on
 * since the finding was produced, the anchor stops matching and we refuse rather
 * than write to a line we no longer recognise.
 */
export function applyLineAutofix(
  content: string,
  autofix: LineAutofix
): ApplyAutofixResult {
  const lines = splitSourceLines(content);

  if (lines.length === 0) {
    return {
      ok: false,
      refusal: "empty-file",
      detail: "The file is empty, so there is no line to patch."
    };
  }

  if (autofix.line < 1 || autofix.line > lines.length) {
    return {
      ok: false,
      refusal: "line-out-of-range",
      detail: `The file has ${lines.length} line(s), so line ${autofix.line} does not exist.`
    };
  }

  const target = lines[autofix.line - 1];

  if (target.text !== autofix.before) {
    return {
      ok: false,
      refusal: "content-drift",
      detail: `Line ${autofix.line} no longer matches the reviewed content. Run \`/superdocs review\` to refresh findings.`
    };
  }

  if (autofix.after === autofix.before) {
    return {
      ok: false,
      refusal: "no-op",
      detail: "The suggested fix is identical to the current line."
    };
  }

  const patched = [...lines];
  patched[autofix.line - 1] = {
    text: autofix.after,
    terminator: target.terminator
  };

  const nextContent = joinSourceLines(patched);

  return {
    ok: true,
    content: nextContent,
    changedLines: changedLineNumbers(content, nextContent)
  };
}

/**
 * Reports which 1-based line numbers differ between two revisions. The apply
 * runner uses this to prove a patch touched only the line it promised to touch,
 * instead of asserting it.
 */
export function changedLineNumbers(before: string, after: string): number[] {
  const beforeLines = splitSourceLines(before);
  const afterLines = splitSourceLines(after);
  const length = Math.max(beforeLines.length, afterLines.length);
  const changed: number[] = [];

  for (let index = 0; index < length; index += 1) {
    const beforeLine = beforeLines[index];
    const afterLine = afterLines[index];

    if (
      beforeLine?.text !== afterLine?.text ||
      beforeLine?.terminator !== afterLine?.terminator
    ) {
      changed.push(index + 1);
    }
  }

  return changed;
}

/**
 * Splits content into lines while remembering each line's own terminator, so a
 * patched file keeps the mixed or non-LF line endings it arrived with.
 */
function splitSourceLines(content: string): SourceLine[] {
  const lines: SourceLine[] = [];
  let start = 0;

  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];

    if (char === "\n") {
      lines.push({ text: content.slice(start, index), terminator: "\n" });
      start = index + 1;
      continue;
    }

    if (char === "\r") {
      const isCrLf = content[index + 1] === "\n";
      lines.push({
        text: content.slice(start, index),
        terminator: isCrLf ? "\r\n" : "\r"
      });
      if (isCrLf) index += 1;
      start = index + 1;
    }
  }

  if (start < content.length) {
    lines.push({ text: content.slice(start), terminator: "" });
  }

  return lines;
}

function joinSourceLines(lines: SourceLine[]): string {
  return lines.map((line) => `${line.text}${line.terminator}`).join("");
}
