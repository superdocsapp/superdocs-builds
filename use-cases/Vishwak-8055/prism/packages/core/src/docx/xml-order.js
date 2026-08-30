// @ts-check
/**
 * fast-xml-parser's default (preserveOrder: false) mode groups same-tag
 * siblings into arrays keyed by tag name — great for "give me all
 * paragraphs," useless for "was this table before or after that
 * paragraph." That interleaving is exactly what table-aware write-back
 * needs, so this module does one narrow, separate preserveOrder:true
 * parse just to recover body-level sibling order, rather than converting
 * the whole document model (and every existing paragraph-reading test) to
 * preserveOrder:true.
 */
import { XMLParser } from 'fast-xml-parser';
import { XML_OPTIONS } from './xml-config.js';

// Full fidelity (attributes included) — this parser's node objects are used
// directly for verbatim table pass-through on write, not just for counting
// tag order, so dropping attributes here would silently corrupt tables
// (e.g. <w:gridCol> without its required w:w width attribute).
const orderParser = new XMLParser({ ...XML_OPTIONS, preserveOrder: true });

function findChild(nodeArray, tagName) {
  for (const node of nodeArray) {
    if (Object.prototype.hasOwnProperty.call(node, tagName)) return node[tagName];
  }
  return null;
}

/**
 * @param {string} xml - raw word/document.xml content
 * @returns {Array<Record<string, any>>} the actual preserveOrder:true body-child nodes, in real document order — e.g. [{'w:p': [...]}, {'w:tbl': [...], ':@': {...}}, {'w:sectPr': [...]}]
 */
export function getOrderedBodyChildren(xml) {
  const parsed = orderParser.parse(xml);
  const documentChildren = findChild(parsed, 'w:document');
  if (!documentChildren) throw new Error('getOrderedBodyChildren: no <w:document> element found — is this valid word/document.xml?');
  const bodyChildren = findChild(documentChildren, 'w:body');
  if (!bodyChildren) throw new Error('getOrderedBodyChildren: no <w:body> element found inside <w:document>');
  return bodyChildren;
}

/**
 * @param {string} xml - raw word/document.xml content
 * @returns {string[]} top-level <w:body> child tag names, in real document order, e.g. ['w:p','w:p','w:tbl','w:p','w:sectPr']
 */
export function getBodyBlockOrder(xml) {
  return getOrderedBodyChildren(xml)
    .map((node) => Object.keys(node).find((k) => k !== ':@'))
    .filter(Boolean);
}
