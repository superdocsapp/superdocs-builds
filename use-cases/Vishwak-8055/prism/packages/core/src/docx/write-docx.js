// @ts-check
/**
 * Writes a new paragraph sequence back into a real .docx.
 *
 * Strategy: reuse the ENTIRE original zip (styles.xml, fontTable.xml,
 * settings.xml, media, everything) and replace only the word/document.xml
 * entry. Within document.xml, only <w:body><w:p>...</w:p></w:body> is
 * rebuilt — <w:sectPr> (page size/margins) and the <w:document> root's
 * namespace attributes are carried over from the source untouched, via the
 * `rawDocument` object read-docx.js already parsed.
 *
 * Two write paths, deliberately kept separate rather than unified into one
 * more-complex function:
 *   - No tables in the source: the original, simple, already-tested path
 *     (preserveOrder:false builder) — unchanged by this addition.
 *   - Tables present: a table-aware path (preserveOrder:true builder,
 *     since correct interleaving of <w:p>/<w:tbl> siblings requires order
 *     info the simple path's grouped object model doesn't have — see
 *     xml-order.js). Tables are passed through VERBATIM (never edited,
 *     never regenerated) and re-anchored at their original position
 *     relative to the paragraph sequence. This only works when the
 *     paragraph COUNT is unchanged (no structural add/remove) — with a
 *     changed count, table anchors are no longer well-defined relative to
 *     new paragraph positions, so that combination still refuses, now
 *     with a narrower, more precise explanation than the old blanket
 *     "any table = refuse."
 */
import JSZip from 'jszip';
import { readFile, writeFile } from 'node:fs/promises';
import { xmlBuilder, xmlBuilderOrdered, XML_DECLARATION } from './xml-config.js';

function buildRunProps(run) {
  const rPr = {};
  if (run.bold) rPr['w:b'] = '';
  if (run.italic) rPr['w:i'] = '';
  if (run.underline) rPr['w:u'] = { '@_w:val': 'single' };
  return Object.keys(rPr).length > 0 ? rPr : undefined;
}

function buildRun(run) {
  const node = { 'w:t': { '@_xml:space': 'preserve', '#text': run.text } };
  const rPr = buildRunProps(run);
  if (rPr) node['w:rPr'] = rPr;
  return node;
}

function buildParagraphNode(paragraph) {
  const node = {};
  if (paragraph.styleId) {
    node['w:pPr'] = { 'w:pStyle': { '@_w:val': paragraph.styleId } };
  }
  const runs =
    paragraph.runs && paragraph.runs.length > 0
      ? paragraph.runs
      : paragraph.text
        ? [{ text: paragraph.text, bold: false, italic: false, underline: false }]
        : [];
  if (runs.length > 0) {
    node['w:r'] = runs.map(buildRun);
  }
  return node;
}

// --- Order-preserving (preserveOrder:true) equivalents, for the table-aware path ---

function buildRunOrdered(run) {
  const children = [];
  const rPrChildren = [];
  if (run.bold) rPrChildren.push({ 'w:b': [] });
  if (run.italic) rPrChildren.push({ 'w:i': [] });
  if (run.underline) rPrChildren.push({ 'w:u': [], ':@': { '@_w:val': 'single' } });
  if (rPrChildren.length > 0) children.push({ 'w:rPr': rPrChildren });
  children.push({ 'w:t': [{ '#text': run.text }], ':@': { '@_xml:space': 'preserve' } });
  return { 'w:r': children };
}

function buildParagraphNodeOrdered(paragraph) {
  const children = [];
  if (paragraph.styleId) {
    children.push({ 'w:pPr': [{ 'w:pStyle': [], ':@': { '@_w:val': paragraph.styleId } }] });
  }
  const runs =
    paragraph.runs && paragraph.runs.length > 0
      ? paragraph.runs
      : paragraph.text
        ? [{ text: paragraph.text, bold: false, italic: false, underline: false }]
        : [];
  for (const r of runs) children.push(buildRunOrdered(r));
  return { 'w:p': children };
}

function extractDocumentAttrs(rawDocument) {
  const attrs = {};
  for (const k of Object.keys(rawDocument)) {
    if (k.startsWith('@_')) attrs[k] = rawDocument[k];
  }
  return attrs;
}

/**
 * Interleaves new paragraphs with the original (unchanged) tables at their
 * original anchor positions, then any trailing nodes (w:sectPr).
 */
function buildOrderedBodyChildren(newParagraphs, tables, trailingOrderedNodes) {
  const tablesByAnchor = new Map();
  for (const t of tables) {
    if (!tablesByAnchor.has(t.precedingParagraphCount)) tablesByAnchor.set(t.precedingParagraphCount, []);
    tablesByAnchor.get(t.precedingParagraphCount).push(t.orderedNode);
  }
  const ordered = [...(tablesByAnchor.get(0) || [])];
  newParagraphs.forEach((p, i) => {
    ordered.push(buildParagraphNodeOrdered(p));
    ordered.push(...(tablesByAnchor.get(i + 1) || []));
  });
  ordered.push(...trailingOrderedNodes);
  return ordered;
}

async function writeSimple(sourceDoc, newParagraphs) {
  const newBody = { ...sourceDoc.rawDocument['w:body'] };
  newBody['w:p'] = newParagraphs.map(buildParagraphNode);
  const newDocumentRoot = { 'w:document': { ...sourceDoc.rawDocument, 'w:body': newBody } };
  const newXml = XML_DECLARATION + xmlBuilder.build(newDocumentRoot);
  return newXml;
}

async function writeTableAware(sourceDoc, newParagraphs) {
  if (newParagraphs.length !== sourceDoc.paragraphs.length) {
    throw new Error(
      `writeDocx refuses: the source document contains ${sourceDoc.tables.length} table(s) AND the paragraph ` +
        `count changed (${sourceDoc.paragraphs.length} -> ${newParagraphs.length} — a structural add/remove). ` +
        'Table anchor positions are only well-defined when paragraph count is unchanged. Tables ARE supported ' +
        'for edits/approvals that modify paragraph content without adding or removing paragraphs.',
    );
  }
  const bodyChildren = buildOrderedBodyChildren(newParagraphs, sourceDoc.tables, sourceDoc.trailingOrderedNodes);
  const documentAttrs = extractDocumentAttrs(sourceDoc.rawDocument);
  const ordered = [
    {
      'w:document': [{ 'w:body': bodyChildren }],
      ...(Object.keys(documentAttrs).length > 0 ? { ':@': documentAttrs } : {}),
    },
  ];
  return XML_DECLARATION + xmlBuilderOrdered.build(ordered);
}

/**
 * @param {{sourcePath: string, rawDocument: object, hasTables: boolean, tables: object[], trailingOrderedNodes: object[], paragraphs: object[]}} sourceDoc - the readDocx() result for the file this write is based on
 * @param {Array<{text: string, styleId: string|null, runs?: Array<{text:string,bold:boolean,italic:boolean,underline:boolean}>}>} newParagraphs
 * @param {string} outputPath
 */
export async function writeDocx(sourceDoc, newParagraphs, outputPath) {
  const newXml = sourceDoc.hasTables
    ? await writeTableAware(sourceDoc, newParagraphs)
    : await writeSimple(sourceDoc, newParagraphs);

  const originalBuf = await readFile(sourceDoc.sourcePath);
  const zip = await JSZip.loadAsync(originalBuf);
  zip.file('word/document.xml', newXml);
  const outBuf = await zip.generateAsync({ type: 'nodebuffer' });
  await writeFile(outputPath, outBuf);
  return { outputPath };
}
