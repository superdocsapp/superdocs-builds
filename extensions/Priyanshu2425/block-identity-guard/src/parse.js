/**
 * A small, tolerant HTML parser.
 *
 * Why hand-written rather than a dependency: this package has to run inside
 * whatever repository already owns the editor integration, in CI, on Node and in
 * a browser test runner, and it has to give the *same* answer everywhere. A DOM
 * parser is not available in Node, and `DOMParser` in a browser normalises
 * markup differently from JSDOM, which would make findings environment-specific
 * -- exactly the class of bug this tool exists to catch.
 *
 * It is deliberately not a spec-compliant parser. It handles what SuperDocs
 * document HTML and editor serialisers actually emit: elements, attributes,
 * comments, doctypes, void elements, raw-text elements, and the common
 * unclosed-tag cases (`<p>`, `<li>`, table cells).
 */

const VOID_ELEMENTS = new Set([
  'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr',
]);

/** Elements whose content is text, not markup. */
const RAW_TEXT_ELEMENTS = new Set(['script', 'style', 'textarea', 'title']);

/** Opening `key` implicitly closes any of `value` sitting open on the stack. */
const IMPLICITLY_CLOSES = new Map([
  ['p', new Set(['p'])],
  ['li', new Set(['li'])],
  ['dt', new Set(['dt', 'dd'])],
  ['dd', new Set(['dt', 'dd'])],
  ['tr', new Set(['tr', 'td', 'th'])],
  ['td', new Set(['td', 'th'])],
  ['th', new Set(['td', 'th'])],
  ['thead', new Set(['thead', 'tbody', 'tfoot', 'tr', 'td', 'th'])],
  ['tbody', new Set(['thead', 'tbody', 'tfoot', 'tr', 'td', 'th'])],
  ['tfoot', new Set(['thead', 'tbody', 'tfoot', 'tr', 'td', 'th'])],
  ['option', new Set(['option'])],
]);

/** Block-ish tags close an open `<p>`. */
const CLOSES_PARAGRAPH = new Set([
  'address', 'article', 'aside', 'blockquote', 'details', 'div', 'dl', 'fieldset',
  'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'header', 'hr', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'ul',
]);

const NAMED_ENTITIES = new Map(Object.entries({
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  ndash: '–', mdash: '—', lsquo: '‘', rsquo: '’',
  ldquo: '“', rdquo: '”', hellip: '…', copy: '©',
  reg: '®', trade: '™', deg: '°', middot: '·',
  bull: '•', laquo: '«', raquo: '»', eacute: 'é',
  egrave: 'è', agrave: 'à', ccedil: 'ç', uuml: 'ü',
  ouml: 'ö', auml: 'ä', szlig: 'ß', euro: '€',
  pound: '£', sect: '§', para: '¶', times: '×',
}));

const ENTITY_PATTERN = /&(#x[0-9a-f]+|#[0-9]+|[a-z][a-z0-9]*);/gi;

/**
 * Decode the entities that matter for text comparison. An editor that re-encodes
 * `&` as `&amp;` has not changed the text, and must not be reported as if it had.
 */
export function decodeEntities(value) {
  if (!value.includes('&')) return value;
  return value.replace(ENTITY_PATTERN, (whole, body) => {
    if (body[0] === '#') {
      const code = body[1] === 'x' || body[1] === 'X'
        ? Number.parseInt(body.slice(2), 16)
        : Number.parseInt(body.slice(1), 10);
      if (!Number.isFinite(code) || code < 0 || code > 0x10ffff) return whole;
      try {
        return String.fromCodePoint(code);
      } catch {
        return whole;
      }
    }
    const named = NAMED_ENTITIES.get(body.toLowerCase());
    return named === undefined ? whole : named;
  });
}

/** Collapse the differences every serialiser introduces and no human intended. */
export function normaliseText(value) {
  return decodeEntities(value)
    .replace(/ /g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .normalize('NFC');
}

export class ElementNode {
  constructor(tag, attributes, start, parent) {
    /** @type {string} */
    this.tag = tag;
    /** @type {Map<string, string>} */
    this.attributes = attributes;
    /** Offset of the `<` that opened this element. */
    this.start = start;
    /** @type {ElementNode | null} */
    this.parent = parent;
    /** @type {ElementNode[]} */
    this.children = [];
    /** Text and child elements, in source order. @type {Array<string|ElementNode>} */
    this.contents = [];
    /** Document order across every element in the tree, 0-based. */
    this.order = -1;
    this.depth = parent ? parent.depth + 1 : 0;
    this._text = null;
  }

  attr(name) {
    return this.attributes.get(name);
  }

  /** Normalised text of this element and everything under it. */
  text() {
    if (this._text === null) this._text = normaliseText(this.rawText());
    return this._text;
  }

  /**
   * Text with element boundaries treated as word boundaries. Two table cells are
   * two words, not one: without the space, "Direct losses" and "Recoverable in
   * full" become "Direct lossesRecoverable", and a comparison that should have
   * matched a flattened list does not.
   */
  rawText() {
    let out = '';
    const walk = (node) => {
      for (const entry of node.contents) {
        if (typeof entry === 'string') {
          out += entry;
        } else {
          out += ' ';
          walk(entry);
          out += ' ';
        }
      }
    };
    walk(this);
    return out;
  }
}

/**
 * @param {string} html
 * @returns {{ root: ElementNode, elements: ElementNode[], source: string }}
 */
export function parseHtml(html) {
  const source = typeof html === 'string' ? html : String(html ?? '');
  const root = new ElementNode('#document', new Map(), 0, null);
  root.depth = -1;

  /** @type {ElementNode[]} */
  const elements = [];
  /** @type {ElementNode[]} */
  const stack = [root];
  const top = () => stack[stack.length - 1];

  const pushText = (text) => {
    if (!text) return;
    top().contents.push(text);
  };

  const popTo = (tag) => {
    for (let i = stack.length - 1; i > 0; i -= 1) {
      if (stack[i].tag === tag) {
        stack.length = i;
        return true;
      }
    }
    return false;
  };

  const closeImplicitly = (tag) => {
    const closes = IMPLICITLY_CLOSES.get(tag);
    while (stack.length > 1) {
      const openTag = top().tag;
      const byTable = closes ? closes.has(openTag) : false;
      const byParagraph = openTag === 'p' && CLOSES_PARAGRAPH.has(tag);
      if (!byTable && !byParagraph) break;
      stack.pop();
    }
  };

  let cursor = 0;
  while (cursor < source.length) {
    const next = source.indexOf('<', cursor);
    if (next === -1) {
      pushText(source.slice(cursor));
      break;
    }
    if (next > cursor) pushText(source.slice(cursor, next));

    // Comment, CDATA or doctype: skipped, but never allowed to swallow content.
    if (source.startsWith('<!--', next)) {
      const end = source.indexOf('-->', next + 4);
      cursor = end === -1 ? source.length : end + 3;
      continue;
    }
    if (source.startsWith('<![CDATA[', next)) {
      const end = source.indexOf(']]>', next + 9);
      if (end === -1) { cursor = source.length; continue; }
      pushText(source.slice(next + 9, end));
      cursor = end + 3;
      continue;
    }
    if (source.startsWith('<!', next) || source.startsWith('<?', next)) {
      const end = source.indexOf('>', next);
      cursor = end === -1 ? source.length : end + 1;
      continue;
    }

    if (source.startsWith('</', next)) {
      const end = source.indexOf('>', next);
      if (end === -1) { pushText(source.slice(next)); break; }
      const tag = source.slice(next + 2, end).trim().toLowerCase();
      if (tag) popTo(tag);
      cursor = end + 1;
      continue;
    }

    const opened = readOpenTag(source, next);
    if (!opened) {
      // A stray `<` that does not begin a tag is text, not markup.
      pushText('<');
      cursor = next + 1;
      continue;
    }

    const { tag, attributes, selfClosing, end } = opened;
    closeImplicitly(tag);

    const node = new ElementNode(tag, attributes, next, top());
    node.order = elements.length;
    elements.push(node);
    top().contents.push(node);
    top().children.push(node);

    if (RAW_TEXT_ELEMENTS.has(tag)) {
      const raw = findRawTextEnd(source, tag, end);
      node.contents.push(source.slice(end, raw.textEnd));
      cursor = raw.next;
      continue;
    }

    if (selfClosing || VOID_ELEMENTS.has(tag)) {
      cursor = end;
      continue;
    }

    stack.push(node);
    cursor = end;
  }

  return { root, elements, source };
}

function readOpenTag(source, at) {
  const nameMatch = /^<([a-zA-Z][a-zA-Z0-9:._-]*)/.exec(source.slice(at, at + 64));
  if (!nameMatch) return null;
  const tag = nameMatch[1].toLowerCase();
  let i = at + nameMatch[0].length;
  const attributes = new Map();
  let selfClosing = false;

  while (i < source.length) {
    while (i < source.length && /\s/.test(source[i])) i += 1;
    if (i >= source.length) break;
    if (source[i] === '>') { i += 1; break; }
    if (source[i] === '/' && source[i + 1] === '>') { selfClosing = true; i += 2; break; }
    if (source[i] === '/') { i += 1; continue; }

    const nameStart = i;
    while (i < source.length && !/[\s=>/]/.test(source[i])) i += 1;
    const name = source.slice(nameStart, i).toLowerCase();
    if (!name) { i += 1; continue; }

    let lookahead = i;
    while (lookahead < source.length && /\s/.test(source[lookahead])) lookahead += 1;
    let value = '';
    if (source[lookahead] === '=') {
      i = lookahead + 1;
      while (i < source.length && /\s/.test(source[i])) i += 1;
      const quote = source[i];
      if (quote === '"' || quote === "'") {
        const close = source.indexOf(quote, i + 1);
        if (close === -1) { value = source.slice(i + 1); i = source.length; }
        else { value = source.slice(i + 1, close); i = close + 1; }
      } else {
        const valueStart = i;
        while (i < source.length && !/[\s>]/.test(source[i])) i += 1;
        value = source.slice(valueStart, i);
      }
    }
    // First occurrence wins, which is what every HTML parser does.
    if (!attributes.has(name)) attributes.set(name, decodeEntities(value));
  }

  return { tag, attributes, selfClosing, end: i };
}

function findRawTextEnd(source, tag, from) {
  const closer = new RegExp('</' + tag + '\\s*>', 'i');
  const rest = source.slice(from);
  const match = closer.exec(rest);
  if (!match) return { textEnd: source.length, next: source.length };
  return { textEnd: from + match.index, next: from + match.index + match[0].length };
}

/** Maps offsets to 1-based line/column, so CI annotations can point at the file. */
export function createPositionLookup(source) {
  const lineStarts = [0];
  for (let i = 0; i < source.length; i += 1) {
    if (source[i] === '\n') lineStarts.push(i + 1);
  }
  return (offset) => {
    let low = 0;
    let high = lineStarts.length - 1;
    while (low < high) {
      const mid = Math.ceil((low + high) / 2);
      if (lineStarts[mid] <= offset) low = mid;
      else high = mid - 1;
    }
    return { line: low + 1, column: offset - lineStarts[low] + 1 };
  };
}

export { VOID_ELEMENTS, RAW_TEXT_ELEMENTS };
