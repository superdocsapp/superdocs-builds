// @ts-check
/**
 * Real OOXML reader for .docx files.
 *
 * A .docx is a ZIP of XML parts (see AGENTS/README of the actual SuperDoc
 * repo: "Built directly on OOXML... no conversion layer"). This module reads
 * word/document.xml directly with jszip + fast-xml-parser rather than going
 * through a DOM/HTML conversion step, for the same fidelity reason SuperDoc
 * itself gives for being OOXML-native.
 *
 * Scope (documented, not hidden): body paragraphs and tables. Headers/
 * footers, comments, and numbering are still out of scope — see
 * README "Known limitations". Table content is read structurally
 * (PRISM GRID) but not diffed/edited — PRISM DELTA still only reasons
 * about paragraphs; tables pass through write-docx.js verbatim.
 */
import JSZip from 'jszip';
import { readFile } from 'node:fs/promises';
import { xmlParser as parser } from './xml-config.js';
import { getOrderedBodyChildren } from './xml-order.js';

/** Normalize a possibly-missing, possibly-singular, possibly-array XML child into an array. */
function asArray(value) {
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value : [value];
}

/**
 * Extract run formatting flags from a <w:rPr> node.
 * @returns {{bold: boolean, italic: boolean, underline: boolean}}
 */
function readRunProps(rPr) {
  if (!rPr) return { bold: false, italic: false, underline: false };
  // OOXML toggle properties are "present and not explicitly w:val=0/false" = on.
  const isOn = (node) => {
    if (node === undefined) return false;
    if (typeof node !== 'object') return true; // self-closing tag parses as '' or true-ish
    const val = node['@_w:val'];
    return val === undefined || val === '1' || val === 'true' || val === true;
  };
  return {
    bold: isOn(rPr['w:b']),
    italic: isOn(rPr['w:i']),
    underline: rPr['w:u'] !== undefined,
  };
}

/**
 * Extract concatenated text + individual runs from a <w:p> node.
 * Word fragments a single visual sentence across many <w:r> runs (spell-check
 * boundaries, revision save points). We concatenate every <w:t> in document
 * order so paragraph-level text is contiguous and diffable, exactly the
 * problem the real SuperDoc skill's merge_runs.py exists to solve on the
 * editing side.
 */
function readParagraph(p, index) {
  const pPr = p['w:pPr'];
  const styleId = pPr?.['w:pStyle']?.['@_w:val'] ?? null;

  const runs = [];
  let text = '';
  for (const r of asArray(p['w:r'])) {
    const rPr = r['w:rPr'];
    const flags = readRunProps(rPr);
    let runText = '';
    for (const t of asArray(r['w:t'])) {
      if (typeof t === 'string') runText += t;
      else if (t && typeof t === 'object' && '#text' in t) runText += String(t['#text']);
    }
    if (runText.length > 0) {
      runs.push({ text: runText, ...flags });
      text += runText;
    }
  }

  return {
    index,
    styleId,
    isHeading: typeof styleId === 'string' && /^Heading/i.test(styleId),
    text,
    runs,
  };
}

/**
 * Vertical-merge state of a table cell. Absent <w:vMerge> = no merge.
 * Self-closing <w:vMerge/> (no w:val) = continuation of a merge started
 * above. <w:vMerge w:val="restart"/> = the first (anchor) cell of a merge.
 */
function readVMerge(tcPr) {
  const node = tcPr?.['w:vMerge'];
  if (node === undefined) return 'none';
  if (typeof node !== 'object') return 'continue';
  return node['@_w:val'] === 'restart' ? 'restart' : 'continue';
}

function readCell(tc, cellIndex) {
  const tcPr = tc['w:tcPr'];
  const gridSpan = tcPr?.['w:gridSpan']?.['@_w:val'] ? Number(tcPr['w:gridSpan']['@_w:val']) : 1;
  const vMerge = readVMerge(tcPr);
  const paragraphs = asArray(tc['w:p']).map((p, i) => readParagraph(p, i));
  return { cellIndex, gridSpan, vMerge, text: paragraphs.map((p) => p.text).join(' '), paragraphs };
}

function readTable(tbl, index, precedingParagraphCount, orderedNode) {
  const rows = asArray(tbl['w:tr']).map((tr, rowIndex) => ({
    rowIndex,
    cells: asArray(tr['w:tc']).map((tc, i) => readCell(tc, i)),
  }));
  const columnCount = rows[0]?.cells.reduce((sum, c) => sum + c.gridSpan, 0) ?? 0;
  return {
    index,
    precedingParagraphCount, // how many body paragraphs appear before this table in real document order — the write-back anchor
    rowCount: rows.length,
    columnCount,
    rows,
    // The order-preserving parse's node for this table — used for verbatim
    // pass-through on write (see write-docx.js's table-aware path). This is
    // a DIFFERENT shape than `tbl` above (which came from the grouped
    // preserveOrder:false parse, used only for readable row/cell
    // extraction); mixing the two shapes on write would silently corrupt
    // output, so they're kept as clearly separate fields.
    orderedNode,
  };
}

/**
 * Read a .docx file into a structured, transparent document model.
 * @param {string} filePath
 * @returns {Promise<{
 *   sourcePath: string,
 *   paragraphs: ReturnType<typeof readParagraph>[],
 *   tables: object[],
 *   hasTables: boolean,
 *   trailingOrderedNodes: object[],
 *   rawDocument: object,
 * }>}
 */
export async function readDocx(filePath) {
  const buf = await readFile(filePath);
  const zip = await JSZip.loadAsync(buf);
  const documentXmlFile = zip.file('word/document.xml');
  if (!documentXmlFile) {
    throw new Error(`Not a valid .docx (missing word/document.xml): ${filePath}`);
  }
  const xml = await documentXmlFile.async('string');
  const parsed = parser.parse(xml);

  const body = parsed?.['w:document']?.['w:body'];
  if (!body) {
    throw new Error(`word/document.xml has no <w:body> — is this a valid OOXML document? ${filePath}`);
  }

  const paragraphs = asArray(body['w:p']).map((p, i) => readParagraph(p, i));
  const rawTables = asArray(body['w:tbl']);

  const tables = [];
  const trailingOrderedNodes = [];
  if (rawTables.length > 0) {
    // Recover real document order to anchor each table to "comes after N
    // paragraphs" — the grouped (preserveOrder:false) parse above cannot
    // tell us this, since it bucketed all w:p together and all w:tbl
    // together, losing their original interleaving. This also captures
    // each table's order-preserving node directly, for verbatim
    // pass-through on write (see readTable's orderedNode field).
    const orderedChildren = getOrderedBodyChildren(xml);
    let paragraphsSeen = 0;
    let tableCursor = 0;
    for (const node of orderedChildren) {
      if (node['w:p'] !== undefined) paragraphsSeen++;
      else if (node['w:tbl'] !== undefined) {
        tables.push(readTable(rawTables[tableCursor], tableCursor, paragraphsSeen, node));
        tableCursor++;
      } else {
        // Anything else at body level (in practice: w:sectPr, always last)
        // — captured in order-preserving shape so write-docx.js can
        // reconstruct the body fully without mixing parser shapes.
        trailingOrderedNodes.push(node);
      }
    }
  }

  return {
    sourcePath: filePath,
    paragraphs,
    tables,
    hasTables: rawTables.length > 0,
    // Body-level nodes after the last table/paragraph (in practice just
    // w:sectPr), in order-preserving shape — only populated when tables
    // exist, since only the table-aware write path needs them.
    trailingOrderedNodes,
    // Raw parsed <w:document> root (namespace attributes + full body),
    // kept for round-trip writing so write-docx.js can preserve everything
    // this reader doesn't model (w:sectPr, namespace declarations, etc.)
    // by replacing only w:body.w:p. Not part of the paragraph contract —
    // write-docx.js is the only intended consumer.
    rawDocument: parsed['w:document'],
  };
}
