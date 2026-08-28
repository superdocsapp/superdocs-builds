export type ProtectedValueKind =
  | 'currency'
  | 'percentage'
  | 'date'
  | 'duration'
  | 'time'
  | 'url'
  | 'identifier'
  | 'decimal'
  | 'integer';

export interface ExtractedValue {
  kind: ProtectedValueKind;
  raw: string;
  normalized: string;
  start: number;
  /** 0-based position among values of the same kind within this text, used to pair before/after values positionally. */
  index: number;
}

const MONTHS = [
  'january', 'february', 'march', 'april', 'may', 'june',
  'july', 'august', 'september', 'october', 'november', 'december',
];

interface RawMatch {
  kind: ProtectedValueKind;
  raw: string;
  start: number;
  end: number;
}

// Highest priority first: a match found by an earlier pattern claims its
// character span, so e.g. the "2027" inside a date is never separately
// reported as a bare integer, and "$1,000" is never separately reported as
// a bare decimal.
const PATTERNS: { kind: ProtectedValueKind; pattern: RegExp }[] = [
  { kind: 'url', pattern: /\bhttps?:\/\/[^\s)>\]]+/g },
  { kind: 'currency', pattern: /\$\s?\d[\d,]*(?:\.\d{1,2})?\b/g },
  { kind: 'date', pattern: /\b\d{4}-\d{2}-\d{2}\b/g },
  {
    kind: 'date',
    pattern:
      /\b(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}\b/gi,
  },
  {
    kind: 'date',
    pattern:
      /\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b/gi,
  },
  { kind: 'date', pattern: /\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/g },
  { kind: 'duration', pattern: /\b\d+(?:\.\d+)?\s?(?:days?|weeks?|months?|years?|hours?|minutes?)\b/gi },
  { kind: 'time', pattern: /\b\d{1,2}:\d{2}\s?(?:AM|PM|am|pm)?\b/g },
  { kind: 'identifier', pattern: /\b(?:Section|Clause|Exhibit|Schedule|Article|Appendix)\s?\d+(?:\.\d+)*\b/gi },
  { kind: 'identifier', pattern: /§\s?\d+(?:\.\d+)*\b/g },
  { kind: 'percentage', pattern: /\b\d+(?:\.\d+)?\s?%/g },
  { kind: 'decimal', pattern: /\b\d+\.\d+\b/g },
  { kind: 'integer', pattern: /\b\d+\b/g },
];

export function extractProtectedValues(text: string): ExtractedValue[] {
  const claimed: { start: number; end: number }[] = [];
  const accepted: RawMatch[] = [];

  const overlaps = (start: number, end: number) => claimed.some((c) => start < c.end && end > c.start);

  for (const { kind, pattern } of PATTERNS) {
    // Fresh RegExp per use — the module-level PATTERNS array holds `g`
    // regexes and `.exec` in a loop would carry lastIndex state across calls.
    const re = new RegExp(pattern.source, pattern.flags);
    for (const match of text.matchAll(re)) {
      const start = match.index ?? 0;
      const end = start + match[0].length;
      if (overlaps(start, end)) continue;
      claimed.push({ start, end });
      accepted.push({ kind, raw: match[0], start, end });
    }
  }

  accepted.sort((a, b) => a.start - b.start);

  const indexByKind = new Map<ProtectedValueKind, number>();
  return accepted.map((m) => {
    const index = indexByKind.get(m.kind) ?? 0;
    indexByKind.set(m.kind, index + 1);
    return { kind: m.kind, raw: m.raw, normalized: normalizeValue(m.kind, m.raw), start: m.start, index };
  });
}

export function normalizeValue(kind: ProtectedValueKind, raw: string): string {
  switch (kind) {
    case 'currency': {
      const amount = parseFloat(raw.replace(/[$,]/g, ''));
      return `USD:${amount.toFixed(2)}`;
    }
    case 'percentage': {
      const amount = parseFloat(raw.replace(/%/, ''));
      return `PCT:${amount}`;
    }
    case 'date':
      return normalizeDate(raw) ?? `UNPARSED_DATE:${raw.trim().toLowerCase()}`;
    case 'duration': {
      const match = /(\d+(?:\.\d+)?)\s?(day|week|month|year|hour|minute)s?/i.exec(raw);
      if (!match) return `UNPARSED_DURATION:${raw}`;
      return `DUR:${match[1]}:${match[2].toLowerCase()}`;
    }
    case 'time':
      return normalizeTime(raw) ?? `UNPARSED_TIME:${raw}`;
    case 'url':
      return raw.replace(/[.,;:]+$/, '');
    case 'identifier':
      return raw.replace(/§/, 'SECTION').replace(/\s+/g, ' ').trim().toUpperCase().replace(/^(\S+)\s+/, '$1:');
    case 'decimal':
      return parseFloat(raw).toString();
    case 'integer':
      return parseInt(raw.replace(/,/g, ''), 10).toString();
  }
}

function normalizeDate(raw: string): string | null {
  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (iso) return raw;

  const monthFirst = /^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$/.exec(raw);
  if (monthFirst) {
    const monthIndex = MONTHS.indexOf(monthFirst[1].toLowerCase());
    if (monthIndex >= 0) {
      return `${monthFirst[3]}-${String(monthIndex + 1).padStart(2, '0')}-${monthFirst[2].padStart(2, '0')}`;
    }
  }

  const dayFirst = /^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/.exec(raw);
  if (dayFirst) {
    const monthIndex = MONTHS.indexOf(dayFirst[2].toLowerCase());
    if (monthIndex >= 0) {
      return `${dayFirst[3]}-${String(monthIndex + 1).padStart(2, '0')}-${dayFirst[1].padStart(2, '0')}`;
    }
  }

  const slash = /^(\d{1,2})\/(\d{1,2})\/(\d{2,4})$/.exec(raw);
  if (slash) {
    const [, m, d, yRaw] = slash;
    const year = yRaw.length === 2 ? (Number(yRaw) < 70 ? `20${yRaw}` : `19${yRaw}`) : yRaw;
    return `${year}-${m.padStart(2, '0')}-${d.padStart(2, '0')}`;
  }

  return null;
}

function normalizeTime(raw: string): string | null {
  const match = /^(\d{1,2}):(\d{2})\s?(AM|PM|am|pm)?$/.exec(raw.trim());
  if (!match) return null;
  let hour = Number(match[1]);
  const minute = match[2];
  const meridiem = match[3]?.toUpperCase();
  if (meridiem === 'PM' && hour < 12) hour += 12;
  if (meridiem === 'AM' && hour === 12) hour = 0;
  return `${String(hour).padStart(2, '0')}:${minute}`;
}
