// Minimal source edits, and the proof that they were minimal.
//
// A repair is expressed as a list of {offset, length, content} splices against
// the ORIGINAL bytes — never as parse-then-reserialise. That is what lets a
// comment, a trailing comma, a CRLF line ending and a BOM survive a fix, and
// it is what makes `only the target changed` an assertion rather than a hope.

import { applyEdits, modify, type Edit, type FormattingOptions } from "jsonc-parser";

export interface TextEdit {
  offset: number;
  length: number;
  content: string;
}

export const BOM = "\uFEFF";

/**
 * Everything outside the edited spans must be byte-identical.
 *
 * This is the safety property of the whole feature, so it is checked against
 * the actual before/after text rather than trusted from the editor that
 * produced the edits. If it ever fails we have reformatted someone's file.
 */
export function assertOnlySpansChanged(
  before: string,
  after: string,
  edits: TextEdit[],
): { ok: true } | { ok: false; reason: string } {
  const ordered = [...edits].sort((a, b) => a.offset - b.offset);

  let beforeCursor = 0;
  let afterCursor = 0;
  const beforeKept: string[] = [];
  const afterKept: string[] = [];

  for (const edit of ordered) {
    if (edit.offset < beforeCursor) {
      return { ok: false, reason: "edits overlap" };
    }
    beforeKept.push(before.slice(beforeCursor, edit.offset));
    afterKept.push(after.slice(afterCursor, afterCursor + (edit.offset - beforeCursor)));
    afterCursor += edit.offset - beforeCursor;
    beforeCursor = edit.offset + edit.length;
    afterCursor += edit.content.length;
  }

  beforeKept.push(before.slice(beforeCursor));
  afterKept.push(after.slice(afterCursor));

  const untouchedBefore = beforeKept.join("");
  const untouchedAfter = afterKept.join("");
  if (untouchedBefore !== untouchedAfter) {
    // Find the divergence so the message points somewhere useful, but NEVER
    // include surrounding source here. This error flows to --fix text and JSON
    // output; config source can contain an Authorization value.
    let i = 0;
    while (i < untouchedBefore.length && untouchedBefore[i] === untouchedAfter[i]) i++;
    return {
      ok: false,
      reason: `bytes outside the edited spans changed near offset ${i}`,
    };
  }
  return { ok: true };
}

export function applyTextEdits(text: string, edits: TextEdit[]): string {
  // Back to front, so earlier offsets stay valid.
  const ordered = [...edits].sort((a, b) => b.offset - a.offset);
  let out = text;
  for (const edit of ordered) {
    out = out.slice(0, edit.offset) + edit.content + out.slice(edit.offset + edit.length);
  }
  return out;
}

// ── JSON / JSONC ─────────────────────────────────────────────────────────

/** Indentation inferred from the file, so an edit matches its surroundings
 *  rather than imposing a house style on someone else's document. */
export function detectFormatting(text: string): FormattingOptions {
  const tabbed = /^\t+["{]/m.test(text);
  if (tabbed) return { tabSize: 1, insertSpaces: false, eol: detectEol(text) };
  const match = /^([ ]+)"/m.exec(text);
  return {
    tabSize: match ? match[1]!.length : 2,
    insertSpaces: true,
    eol: detectEol(text),
  };
}

export function detectEol(text: string): string {
  return text.includes("\r\n") ? "\r\n" : "\n";
}

/**
 * Edits that set `path` to `value` in a JSON or JSONC document.
 *
 * jsonc-parser's `modify` is the reason JSONC was proven in TypeScript first:
 * it returns splices against the original text, so comments, trailing commas
 * and formatting elsewhere are untouched by construction.
 */
export function jsonEdits(
  text: string,
  path: (string | number)[],
  value: unknown,
): TextEdit[] {
  const bom = text.startsWith(BOM);
  const body = bom ? text.slice(BOM.length) : text;

  const edits: Edit[] = modify(body, path, value, {
    formattingOptions: detectFormatting(body),
  });

  return edits.map((e) => ({
    // Shift past the BOM so offsets address the original bytes. Without this a
    // fix on a BOM'd file lands one character early and corrupts it.
    offset: e.offset + (bom ? BOM.length : 0),
    length: e.length,
    content: e.content,
  }));
}

/** Apply through jsonc-parser so its own formatting rules are honoured. */
export function applyJsonEdits(text: string, edits: TextEdit[]): string {
  const bom = text.startsWith(BOM);
  const body = bom ? text.slice(BOM.length) : text;
  const shifted: Edit[] = edits.map((e) => ({
    offset: e.offset - (bom ? BOM.length : 0),
    length: e.length,
    content: e.content,
  }));
  return (bom ? BOM : "") + applyEdits(body, shifted);
}

// ── TOML ─────────────────────────────────────────────────────────────────
//
// smol-toml validates but gives no spans, so the target is located in the
// source text. Deliberately narrow: it finds `key = <value>` inside a named
// table and replaces the value only. Anything it cannot locate unambiguously
// returns null, and the caller reports rather than guesses.

export interface TomlTarget {
  table: string;
  key: string;
}

export function tomlValueEdit(
  text: string,
  target: TomlTarget,
  newValue: string,
): TextEdit | null {
  const bom = text.startsWith(BOM);
  const offsetBase = bom ? BOM.length : 0;
  const body = bom ? text.slice(BOM.length) : text;

  // Locate the table header, then the extent of that table: up to the next
  // header at column 0, or end of file.
  const headerPattern = new RegExp(
    `^\\[\\s*${target.table.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\]\\s*$`,
    "m",
  );
  const header = headerPattern.exec(body);
  if (!header) return null;

  const tableStart = header.index + header[0].length;
  const nextHeader = /^\[/m.exec(body.slice(tableStart));
  const tableEnd = nextHeader ? tableStart + nextHeader.index : body.length;
  const section = body.slice(tableStart, tableEnd);

  // `key = "value"` — the quoted form is the only one SuperDocs config uses,
  // and restricting to it keeps the locator honest about what it understands.
  const keyPattern = new RegExp(
    `(^[ \\t]*${target.key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}[ \\t]*=[ \\t]*)(".*?")`,
    "m",
  );
  const found = keyPattern.exec(section);
  if (!found) return null;

  // A second occurrence in the same table means we cannot tell which is meant.
  if (keyPattern.exec(section.slice(found.index + found[0].length))) return null;

  const valueOffset = tableStart + found.index + found[1]!.length;
  return {
    offset: offsetBase + valueOffset,
    length: found[2]!.length,
    content: JSON.stringify(newValue),
  };
}
