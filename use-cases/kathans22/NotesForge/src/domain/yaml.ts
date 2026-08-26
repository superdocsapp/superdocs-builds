/**
 * A hand-rolled parser for the one YAML shape this project's config files
 * use: a top-level `key:` followed by a block sequence of flat records,
 * each record's fields being either a scalar or a block/inline list of
 * scalars. NotesForge is zero-dependency by design, so this is deliberately
 * a subset, not a general YAML engine — anything outside that shape is a
 * parse error rather than a silent guess.
 */

export type YamlScalar = string | number | boolean | null;
export type YamlValue = YamlScalar | string[];

export interface YamlField {
  value: YamlValue;
  line: number;
}

export interface YamlRecord {
  line: number;
  fields: Map<string, YamlField>;
}

export class YamlParseError extends Error {
  constructor(message: string, file: string, line: number) {
    super(`${file}:${line}: ${message}`);
    this.name = "YamlParseError";
  }
}

interface Line {
  raw: string;
  num: number;
  indent: number;
  trimmed: string;
}

function prepLines(text: string): Line[] {
  return text
    .split(/\r?\n/)
    .map((raw, i) => {
      const trimmed = raw.trim();
      const indent = raw.length - raw.trimStart().length;
      return { raw, num: i + 1, indent, trimmed };
    })
    .filter((l) => l.trimmed !== "" && !l.trimmed.startsWith("#"));
}

function parseScalar(raw: string): YamlScalar {
  const t = raw.trim();
  if (t === "" || t === "null" || t === "~") return null;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+$/.test(t)) return Number(t);
  if (/^-?\d+\.\d+$/.test(t)) return Number(t);
  if (t.length >= 2 && t.startsWith('"') && t.endsWith('"')) {
    return t.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  }
  if (t.length >= 2 && t.startsWith("'") && t.endsWith("'")) {
    return t.slice(1, -1).replace(/''/g, "'");
  }
  return t;
}

function splitKeyValue(
  content: string,
  file: string,
  lineNum: number,
): { key: string; valueRaw: string } {
  const m = content.match(/^([A-Za-z_][A-Za-z0-9_]*):(.*)$/);
  if (!m) {
    throw new YamlParseError(`expected "key: value", got "${content}"`, file, lineNum);
  }
  return { key: m[1], valueRaw: m[2] };
}

function consumeField(
  lines: Line[],
  i: number,
  fieldIndent: number,
  key: string,
  valueRaw: string,
  lineNum: number,
  record: YamlRecord,
  file: string,
): number {
  if (record.fields.has(key)) {
    throw new YamlParseError(`duplicate field "${key}"`, file, lineNum);
  }

  const trimmed = valueRaw.trim();

  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    const inner = trimmed.slice(1, -1).trim();
    const items = inner === "" ? [] : inner.split(",").map((s) => String(parseScalar(s.trim())));
    record.fields.set(key, { value: items, line: lineNum });
    return i;
  }

  if (trimmed !== "") {
    record.fields.set(key, { value: parseScalar(trimmed), line: lineNum });
    return i;
  }

  // Empty value: this key may head a block sequence on following lines.
  if (i < lines.length && lines[i].indent > fieldIndent && lines[i].trimmed.startsWith("-")) {
    const listIndent = lines[i].indent;
    const items: string[] = [];
    while (i < lines.length && lines[i].indent === listIndent && lines[i].trimmed.startsWith("-")) {
      const itemContent = lines[i].trimmed.replace(/^-\s?/, "");
      const v = parseScalar(itemContent);
      items.push(v === null ? "" : String(v));
      i++;
    }
    record.fields.set(key, { value: items, line: lineNum });
    return i;
  }

  record.fields.set(key, { value: null, line: lineNum });
  return i;
}

/**
 * Parses `{listKey}:\n  - field: value\n    field: value\n  - ...` into a
 * list of records. Field order and nesting depth are fixed by the first
 * record's indentation; anything that doesn't match that shape is a
 * YamlParseError naming the file and line.
 */
export function parseYamlRecordList(text: string, listKey: string, file: string): YamlRecord[] {
  const lines = prepLines(text);
  const topIdx = lines.findIndex((l) => l.indent === 0 && l.trimmed === `${listKey}:`);
  if (topIdx === -1) {
    throw new YamlParseError(`expected top-level key "${listKey}:"`, file, 1);
  }

  let i = topIdx + 1;
  if (i >= lines.length || !lines[i].trimmed.startsWith("-")) {
    throw new YamlParseError(
      `expected a list item ("- ...") under "${listKey}:"`,
      file,
      lines[topIdx].num,
    );
  }
  const itemIndent = lines[i].indent;
  const fieldIndent = itemIndent + 2;

  const records: YamlRecord[] = [];

  while (i < lines.length && lines[i].indent >= itemIndent) {
    const line = lines[i];
    if (line.indent !== itemIndent || !line.trimmed.startsWith("-")) {
      throw new YamlParseError(
        `unexpected indentation (expected a new "- " item at column ${itemIndent})`,
        file,
        line.num,
      );
    }

    const dashContent = line.trimmed.replace(/^-\s?/, "");
    const record: YamlRecord = { line: line.num, fields: new Map() };
    i++;

    if (dashContent !== "") {
      const { key, valueRaw } = splitKeyValue(dashContent, file, line.num);
      i = consumeField(lines, i, fieldIndent, key, valueRaw, line.num, record, file);
    }

    while (i < lines.length && lines[i].indent === fieldIndent) {
      const fline = lines[i];
      if (fline.trimmed.startsWith("-")) {
        throw new YamlParseError(
          `unexpected list item at field indentation — check indentation`,
          file,
          fline.num,
        );
      }
      const { key, valueRaw } = splitKeyValue(fline.trimmed, file, fline.num);
      i++;
      i = consumeField(lines, i, fieldIndent, key, valueRaw, fline.num, record, file);
    }

    records.push(record);
  }

  return records;
}
