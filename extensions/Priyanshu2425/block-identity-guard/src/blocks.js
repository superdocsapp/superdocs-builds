/**
 * Turns a parsed tree into the two things the diff needs: a list of blocks that
 * carry an identifier, and a locator for every one of them that a human can act
 * on -- tag, position, structural path, text, and the nearest ancestor that is
 * still identifiable.
 */

import { parseHtml, createPositionLookup } from './parse.js';

const PREVIEW_LENGTH = 60;

/** Attributes SuperDocs puts on the wire that carry meaning, not styling. */
export const MEANINGFUL_ATTRIBUTE_PREFIX = 'data-';

/**
 * Attributes that are noise for round-trip purposes: editors legitimately add
 * and remove them, and losing one is not a document-integrity problem.
 */
const IGNORED_DATA_ATTRIBUTES = new Set([
  'data-reactid',
  'data-testid',
  'data-slate-node',
  'data-slate-leaf',
  'data-slate-string',
  'data-node-view-wrapper',
  'data-node-view-content',
  'data-placeholder',
  'data-empty',
]);

export function shortText(text) {
  if (text.length <= PREVIEW_LENGTH) return text;
  return text.slice(0, PREVIEW_LENGTH).trimEnd() + '…';
}

function structuralPath(node) {
  const segments = [];
  let current = node;
  while (current && current.parent && current.parent.tag !== '#document') {
    const parent = current.parent;
    const sameTag = parent.children.filter((child) => child.tag === current.tag);
    const position = sameTag.indexOf(current) + 1;
    segments.push(sameTag.length > 1 ? `${current.tag}[${position}]` : current.tag);
    current = parent;
  }
  if (current) {
    const roots = current.parent ? current.parent.children.filter((c) => c.tag === current.tag) : [current];
    const position = roots.indexOf(current) + 1;
    segments.push(roots.length > 1 ? `${current.tag}[${position}]` : current.tag);
  }
  return segments.reverse().join(' > ');
}

/** Every `data-*` attribute except the identifier itself and known editor noise. */
export function dataAttributes(node, idAttribute) {
  const out = new Map();
  for (const [name, value] of node.attributes) {
    if (name === idAttribute) continue;
    if (!name.startsWith(MEANINGFUL_ATTRIBUTE_PREFIX)) continue;
    if (IGNORED_DATA_ATTRIBUTES.has(name)) continue;
    out.set(name, value);
  }
  return out;
}

/**
 * @param {string} html
 * @param {{ idAttribute: string, label: string }} options
 */
export function indexDocument(html, options) {
  const idAttribute = options.idAttribute;
  const { elements, source } = parseHtml(html);
  const positionOf = createPositionLookup(source);

  /** @type {Block[]} */
  const blocks = [];
  /** @type {Map<string, Block[]>} */
  const byId = new Map();

  for (const node of elements) {
    const id = node.attr(idAttribute);
    if (id === undefined || id === '') continue;
    const position = positionOf(node.start);
    const block = {
      id,
      tag: node.tag,
      node,
      /** Position among identified blocks, 1-based -- what a report should quote. */
      blockIndex: blocks.length + 1,
      elementOrder: node.order,
      depth: node.depth,
      path: structuralPath(node),
      text: node.text(),
      preview: shortText(node.text()),
      line: position.line,
      column: position.column,
      attributes: node.attributes,
      dataAttributes: dataAttributes(node, idAttribute),
      partType: node.attr('data-part-type') || null,
      label: options.label,
    };
    blocks.push(block);
    const existing = byId.get(id);
    if (existing) existing.push(block);
    else byId.set(id, [block]);
  }

  // The nearest ancestor that also carries an identifier: the anchor a reader
  // uses to find the block when its own id is gone.
  const blockByNode = new Map(blocks.map((block) => [block.node, block]));
  for (const block of blocks) {
    let ancestor = block.node.parent;
    while (ancestor) {
      const found = blockByNode.get(ancestor);
      if (found) {
        block.parentId = found.id;
        break;
      }
      ancestor = ancestor.parent;
    }
    if (!block.parentId) block.parentId = null;
  }

  return {
    label: options.label,
    source,
    elements,
    blocks,
    byId,
    ids: new Set(byId.keys()),
    positionOf,
    /** Attribute names seen anywhere in the document, for signature detection. */
    attributeNames: attributeCensus(elements),
    tagNames: new Set(elements.map((node) => node.tag)),
  };
}

function attributeCensus(elements) {
  const census = new Map();
  for (const node of elements) {
    for (const name of node.attributes.keys()) {
      census.set(name, (census.get(name) || 0) + 1);
    }
  }
  return census;
}

/**
 * Common alternatives, used only to produce a better error when the expected
 * attribute is nowhere in the input.
 */
export const KNOWN_ID_ATTRIBUTES = ['data-chunk-id', 'data-chunkid', 'data-block-id', 'data-id'];

export function detectIdAttribute(html) {
  for (const candidate of KNOWN_ID_ATTRIBUTES) {
    if (html.includes(candidate + '=')) return candidate;
  }
  return null;
}
