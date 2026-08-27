/**
 * The check itself: parse both sides, difference the identifiers, diagnose every
 * loss, and separate the things that look like loss but are not (a legal
 * reorder, an out-of-flow part an editor is entitled to omit, a block the user
 * simply edited).
 */

import { indexDocument, detectIdAttribute, shortText } from './blocks.js';
import { buildAfterIndex, findCounterpart, describeNode } from './match.js';
import { computeSignals, diagnoseLostBlock } from './diagnose.js';
import { RULES, CRITICAL_DATA_ATTRIBUTES, severityRank } from './rules.js';

export const SCHEMA_VERSION = 1;
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;
const SUBTREE_GROUP_THRESHOLD = 3;
const SAMPLE_LIMIT = 5;

export function resolveOptions(options = {}) {
  return {
    idAttribute: options.idAttribute || 'data-chunk-id',
    strictParts: options.strictParts === true,
    includeContentChanges: options.includeContentChanges === true,
    maxBytes: options.maxBytes || DEFAULT_MAX_BYTES,
    beforeLabel: options.beforeLabel || 'before',
    afterLabel: options.afterLabel || 'after',
  };
}

/**
 * @param {string} beforeHtml HTML as SuperDocs sent it (a `document_sync` payload)
 * @param {string} afterHtml HTML as your integration serialised it back
 * @param {object} [options]
 */
export function analyse(beforeHtml, afterHtml, options = {}) {
  const settings = resolveOptions(options);
  assertString(beforeHtml, 'beforeHtml');
  assertString(afterHtml, 'afterHtml');
  assertSize(beforeHtml, settings, 'beforeHtml');
  assertSize(afterHtml, settings, 'afterHtml');

  const before = indexDocument(beforeHtml, { idAttribute: settings.idAttribute, label: settings.beforeLabel });
  const after = indexDocument(afterHtml, { idAttribute: settings.idAttribute, label: settings.afterLabel });
  const signals = computeSignals(before, after, settings.idAttribute);

  /** @type {object[]} */
  const findings = [];
  const counts = {
    beforeBlocks: before.blocks.length,
    afterBlocks: after.blocks.length,
    intact: 0,
    lost: 0,
    duplicated: 0,
    moved: 0,
    added: 0,
    partsOmitted: 0,
  };

  if (before.blocks.length === 0) {
    findings.push(noIdentifiersFinding(beforeHtml, settings));
    return buildReport(findings, counts, settings, signals);
  }

  addDuplicateFindings(before, after, findings, counts, settings);

  const survivingIds = [...before.ids].filter((id) => after.ids.has(id));
  const lostBlocks = before.blocks.filter((block) => !after.ids.has(block.id));
  counts.intact = survivingIds.length;
  counts.lost = lostBlocks.length;
  counts.added = [...after.ids].filter((id) => !before.ids.has(id)).length;

  if (survivingIds.length === 0) {
    findings.push(totalLossFinding(before, after, signals, settings));
    return buildReport(findings, counts, settings, signals);
  }

  addLostFindings(lostBlocks, before, after, signals, settings, findings, counts);
  addMovedFindings(before, after, findings, counts);
  addAttributeFindings(before, after, findings, settings);
  addContentChangeFindings(before, after, findings, settings);
  addNewIdFinding(before, after, findings, counts);

  return buildReport(findings, counts, settings, signals);
}

function assertString(value, name) {
  if (typeof value !== 'string') {
    throw new TypeError(`${name} must be a string of HTML, received ${typeof value}`);
  }
}

function assertSize(value, settings, name) {
  if (value.length > settings.maxBytes) {
    throw new RangeError(
      `${name} is ${value.length} characters, above the ${settings.maxBytes} limit. `
      + 'Raise maxBytes if the document really is this large.',
    );
  }
}

function noIdentifiersFinding(beforeHtml, settings) {
  const alternative = detectIdAttribute(beforeHtml);
  const hint = alternative && alternative !== settings.idAttribute
    ? `the document does carry ${alternative}; pass idAttribute: '${alternative}' if that is your identifier`
    : 'capture the HTML from a document_sync event or a chat response, before your editor touches it';
  return finalise({
    rule: RULES.NO_IDS_IN_SOURCE,
    severity: RULES.NO_IDS_IN_SOURCE.severity,
    id: null,
    cause: `no ${settings.idAttribute} attribute anywhere in the before document, so there is nothing to validate`,
    confidence: 'high',
    evidence: [hint],
    locator: null,
    counterpart: null,
    members: [],
  });
}

function totalLossFinding(before, after, signals, settings) {
  const samples = before.blocks.slice(0, SAMPLE_LIMIT).map((block) => locatorOf(block));

  if (after.blocks.length > 0) {
    return finalise({
      rule: RULES.IDS_REGENERATED,
      severity: RULES.IDS_REGENERATED.severity,
      id: null,
      cause:
        `none of the ${before.blocks.length} identifiers survived, and the after document carries `
        + `${after.blocks.length} identifiers of its own: the editor set its own content instead of `
        + 'applying the document_sync HTML, so every subsequent change batch will miss',
      confidence: 'high',
      evidence: [
        `before: ${before.blocks.slice(0, 3).map((b) => b.id).join(', ')}`,
        `after: ${after.blocks.slice(0, 3).map((b) => b.id).join(', ')}`,
        signals.afterIdsLookGenerated
          ? 'the after identifiers have the same shape as SuperDocs identifiers, which is why this failure is easy to miss on inspection'
          : 'the after identifiers do not have the shape SuperDocs generates',
      ],
      locator: null,
      counterpart: null,
      members: samples.map((locator) => ({ id: locator.id, locator, counterpart: null })),
    });
  }

  const strippedByHop = signals.afterVocabularyIsMarkdownOnly && signals.afterDataAttributes === 0;
  return finalise({
    rule: RULES.ALL_IDS_STRIPPED,
    severity: RULES.ALL_IDS_STRIPPED.severity,
    id: null,
    cause: strippedByHop
      ? `all ${before.blocks.length} identifiers are gone and the after document has no data attributes `
        + 'and no tags a markdown round trip cannot express: the whole document went through a markdown '
        + 'or plain-text hop'
      : `all ${before.blocks.length} identifiers are gone while other attributes survived: a sanitiser or `
        + 'editor schema is filtering unknown attributes across the whole document',
    confidence: 'high',
    evidence: [
      `after document keeps ${signals.afterDataAttributes} data attribute(s) of any kind`,
      signals.nonMarkdownTagsGone.length > 0
        ? `tags that did not survive: ${signals.nonMarkdownTagsGone.join(', ')}`
        : 'tag vocabulary is unchanged, so the structure survived and only attributes were filtered',
    ],
    locator: null,
    counterpart: null,
    members: samples.map((locator) => ({ id: locator.id, locator, counterpart: null })),
  });
}

function addDuplicateFindings(before, after, findings, counts, settings) {
  for (const [id, blocks] of before.byId) {
    if (blocks.length < 2) continue;
    findings.push(finalise({
      rule: RULES.DUPLICATE_ID_IN_SOURCE,
      severity: RULES.DUPLICATE_ID_IN_SOURCE.severity,
      id,
      cause:
        `${settings.idAttribute}="${id}" is on ${blocks.length} blocks in the before document, so the `
        + 'input to this round trip is already ambiguous',
      confidence: 'high',
      evidence: ['the blocks carrying it are listed below'],
      locator: locatorOf(blocks[0]),
      counterpart: null,
      members: blocks.map((block) => ({ id, locator: locatorOf(block), counterpart: null })),
    }));
  }

  for (const [id, blocks] of after.byId) {
    if (blocks.length < 2) continue;
    counts.duplicated += 1;
    findings.push(finalise({
      rule: RULES.DUPLICATE_ID,
      severity: RULES.DUPLICATE_ID.severity,
      id,
      cause:
        `${settings.idAttribute}="${id}" is on ${blocks.length} blocks after the round trip -- a copy-paste, `
        + 'a split block, or a node the editor cloned. A change batch targeting this identifier is '
        + 'ambiguous: the edit can land on either node',
      confidence: 'high',
      evidence: [
        'the blocks carrying it are listed below; the edit lands on whichever one your applier '
        + 'finds first, which is not stable between runs',
      ],
      locator: locatorOf(blocks[0]),
      counterpart: null,
      members: blocks.map((block) => ({ id, locator: locatorOf(block), counterpart: null })),
    }));
  }
}

function addLostFindings(lostBlocks, before, after, signals, settings, findings, counts) {
  const index = buildAfterIndex(after);
  const diagnosed = [];

  for (const block of lostBlocks) {
    const match = findCounterpart(block, index);
    const diagnosis = diagnoseLostBlock(block, match, { after, signals, idAttribute: settings.idAttribute });

    // An out-of-flow part that is simply not in the editor's view is documented
    // behaviour, and its absence never deletes it. It is reported, but it is not
    // the same event as an identifier being stripped off a block that is there.
    if (block.partType && !match.node) {
      counts.partsOmitted += 1;
      counts.lost -= 1;
      findings.push(finalise({
        rule: RULES.PART_OMITTED,
        severity: settings.strictParts ? 'error' : RULES.PART_OMITTED.severity,
        id: block.id,
        cause:
          `this block is an out-of-flow part (data-part-type="${block.partType}") and is not in the after `
          + 'document. Omitting one is normal for an editor with no header/footer affordance, and never '
          + 'deletes it: the server treats absence as normal, and deletion needs deleted_part_chunk_ids',
        confidence: 'high',
        evidence: ['run with strictParts if your integration is supposed to render and return parts'],
        locator: locatorOf(block),
        counterpart: null,
        members: [],
      }));
      continue;
    }

    diagnosed.push({ block, diagnosis });
  }

  for (const finding of groupDiagnoses(diagnosed, settings, before, after)) findings.push(finding);
}

/**
 * The first block above this one whose identifier is still in the after
 * document. When a whole region is lost, this is the anchor a reader can
 * actually find, and the boundary the transformation stopped at.
 */
function nearestSurvivingAncestor(block, before, after) {
  const blockById = new Map();
  for (const candidate of before.blocks) if (!blockById.has(candidate.id)) blockById.set(candidate.id, candidate);
  let currentId = block.parentId;
  const seen = new Set();
  while (currentId && !seen.has(currentId)) {
    seen.add(currentId);
    if (after.ids.has(currentId)) return currentId;
    const parent = blockById.get(currentId);
    currentId = parent ? parent.parentId : null;
  }
  return null;
}

/**
 * One transformation usually takes a whole region, not one block. Reporting a
 * markdown hop forty times, once per paragraph, buries the single fact worth
 * knowing: everything under this ancestor came back bare. Losses that share the
 * nearest surviving ancestor are collapsed into one finding that still names
 * every member, so specificity survives the summarising.
 */
function groupDiagnoses(diagnosed, settings, before, after) {
  const groups = new Map();
  for (const entry of diagnosed) {
    const anchor = nearestSurvivingAncestor(entry.block, before, after) || '';
    const existing = groups.get(anchor);
    if (existing) existing.push(entry);
    else groups.set(anchor, [entry]);
  }

  const out = [];
  for (const [anchor, entries] of groups) {
    if (entries.length < SUBTREE_GROUP_THRESHOLD || !anchor) {
      for (const entry of entries) out.push(lostFinding(entry, settings));
      continue;
    }

    const tally = new Map();
    for (const entry of entries) {
      tally.set(entry.diagnosis.rule.code, (tally.get(entry.diagnosis.rule.code) || 0) + 1);
    }
    const dominantCode = dominantRule(tally, entries.length);
    const representative = entries.find((entry) => entry.diagnosis.rule.code === dominantCode).diagnosis;
    const topmost = entries[0].block;
    const mixed = tally.size > 1;

    out.push(finalise({
      rule: RULES.LOST_SUBTREE,
      severity: RULES.LOST_SUBTREE.severity,
      id: anchor,
      idRole: 'anchor',
      cause:
        `${entries.length} blocks under ${anchor} lost identity. The loss starts at `
        + `${topmost.tag} "${topmost.preview}" and the dominant transformation is `
        + `${dominantCode}: ${representative.cause}`,
      confidence: representative.confidence,
      evidence: [
        mixed
          ? `rules in this group: ${[...tally.entries()].map(([code, count]) => `${code} x${count}`).join(', ')}`
          : `every block in this group failed the same way (${dominantCode})`,
        `${anchor} kept its own identifier, so the loss stops there: fix the transformation that `
        + 'takes its children and the whole group is fixed',
      ],
      locator: locatorOf(topmost),
      counterpart: representative.counterpart,
      members: entries.map((entry) => ({
        id: entry.block.id,
        rule: entry.diagnosis.rule.code,
        cause: entry.diagnosis.cause,
        confidence: entry.diagnosis.confidence,
        locator: locatorOf(entry.block),
        counterpart: entry.diagnosis.counterpart,
      })),
    }));
  }
  return out;
}

/**
 * The rule that explains a group.
 *
 * Plain frequency picks the wrong one: after a structural conversion, the
 * containers it flattened all report as removed, and "removed" is the rule that
 * says the least. When something more specific explains a real share of the
 * group, that is the sentence worth putting at the top.
 */
const EXPLANATORY_ORDER = [
  'LOST_MARKDOWN_HOP',
  'LOST_ATTRIBUTE_STRIPPED',
  'LOST_NODE_REBUILT',
  'LOST_BLOCK_REMOVED',
];

function dominantRule(tally, total) {
  const ranked = [...tally.entries()].sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return EXPLANATORY_ORDER.indexOf(a[0]) - EXPLANATORY_ORDER.indexOf(b[0]);
  });
  const [topCode, topCount] = ranked[0];
  if (topCode !== 'LOST_BLOCK_REMOVED' || topCount / total > 0.5 || ranked.length === 1) return topCode;
  return ranked[1][0];
}

function lostFinding(entry, settings) {
  return finalise({
    rule: entry.diagnosis.rule,
    severity: entry.diagnosis.rule.severity,
    id: entry.block.id,
    cause: entry.diagnosis.cause,
    confidence: entry.diagnosis.confidence,
    evidence: entry.diagnosis.evidence,
    locator: locatorOf(entry.block),
    counterpart: entry.diagnosis.counterpart,
    members: [],
  });
}

/**
 * Position changes are only meaningful relative to the blocks that did not move.
 * A single deletion shifts every index after it, so comparing raw positions
 * reports the whole tail of the document as moved. The longest run of blocks
 * still in their original relative order is the document; everything outside it
 * is what actually moved.
 */
function addMovedFindings(before, after, findings, counts) {
  const pairs = [];
  for (const block of before.blocks) {
    const afterBlocks = after.byId.get(block.id);
    if (!afterBlocks || afterBlocks.length !== 1) continue;
    pairs.push({ block, afterBlock: afterBlocks[0] });
  }

  const stable = new Set(longestIncreasingSubsequence(pairs.map((pair) => pair.afterBlock.blockIndex)));
  pairs.forEach((pair, position) => {
    if (stable.has(position)) return;
    counts.moved += 1;
    findings.push(finalise({
      rule: RULES.BLOCK_MOVED,
      severity: RULES.BLOCK_MOVED.severity,
      id: pair.block.id,
      cause:
        `identity intact, position ${pair.block.blockIndex} to ${pair.afterBlock.blockIndex} relative to the `
        + 'blocks that did not move: a reorder, not a loss',
      confidence: 'high',
      evidence: [`path ${pair.block.path} to ${pair.afterBlock.path}`],
      locator: locatorOf(pair.block),
      counterpart: {
        tag: pair.afterBlock.tag,
        line: pair.afterBlock.line,
        column: pair.afterBlock.column,
        preview: pair.afterBlock.preview,
        attributes: [...pair.afterBlock.attributes.keys()],
        hasIdAttribute: true,
      },
      members: [],
    }));
  });
}

/** Returns the indices of one longest increasing subsequence of `values`. */
export function longestIncreasingSubsequence(values) {
  if (values.length === 0) return [];
  const tails = [];
  const tailIndices = [];
  const previous = new Array(values.length).fill(-1);

  for (let i = 0; i < values.length; i += 1) {
    let low = 0;
    let high = tails.length;
    while (low < high) {
      const mid = (low + high) >> 1;
      if (tails[mid] < values[i]) low = mid + 1;
      else high = mid;
    }
    tails[low] = values[i];
    tailIndices[low] = i;
    previous[i] = low > 0 ? tailIndices[low - 1] : -1;
  }

  const result = [];
  let cursor = tailIndices[tails.length - 1];
  while (cursor !== -1) {
    result.push(cursor);
    cursor = previous[cursor];
  }
  return result.reverse();
}

/**
 * Diagram sources, equation sources, citation fields and part markers ride on
 * data attributes and have exactly the same silent failure mode as the
 * identifier: the block survives, the meaning does not.
 */
function addAttributeFindings(before, after, findings, settings) {
  for (const block of before.blocks) {
    const afterBlocks = after.byId.get(block.id);
    if (!afterBlocks || afterBlocks.length !== 1) continue;
    const afterBlock = afterBlocks[0];

    const dropped = [...block.dataAttributes.keys()].filter((name) => !afterBlock.dataAttributes.has(name));
    if (dropped.length === 0) continue;

    const critical = dropped.filter((name) => CRITICAL_DATA_ATTRIBUTES.has(name));
    const consequences = critical.map((name) => `${name}: ${CRITICAL_DATA_ATTRIBUTES.get(name)}`);

    findings.push(finalise({
      rule: RULES.DATA_ATTRIBUTE_DROPPED,
      severity: critical.length > 0 ? 'error' : 'warning',
      id: block.id,
      cause:
        `the block kept ${settings.idAttribute} but lost ${dropped.join(', ')}: the same attribute filter that `
        + 'drops identifiers drops every other data attribute, and these carry content that cannot be '
        + 'recovered from the rendered output',
      confidence: 'high',
      evidence: consequences.length > 0
        ? consequences
        : ['not a known SuperDocs attribute, so the consequence depends on what put it there'],
      locator: locatorOf(block),
      counterpart: {
        tag: afterBlock.tag,
        line: afterBlock.line,
        column: afterBlock.column,
        preview: afterBlock.preview,
        attributes: [...afterBlock.attributes.keys()],
        hasIdAttribute: true,
      },
      members: [],
    }));
  }
}

function addContentChangeFindings(before, after, findings, settings) {
  if (!settings.includeContentChanges) return;
  for (const block of before.blocks) {
    const afterBlocks = after.byId.get(block.id);
    if (!afterBlocks || afterBlocks.length !== 1) continue;
    const afterBlock = afterBlocks[0];
    if (afterBlock.text === block.text) continue;
    findings.push(finalise({
      rule: RULES.CONTENT_CHANGED,
      severity: RULES.CONTENT_CHANGED.severity,
      id: block.id,
      cause: 'identity intact, text changed: ordinary editing, reported because you asked to see it',
      confidence: 'high',
      evidence: [`"${block.preview}" to "${afterBlock.preview}"`],
      locator: locatorOf(block),
      counterpart: {
        tag: afterBlock.tag,
        line: afterBlock.line,
        column: afterBlock.column,
        preview: afterBlock.preview,
        attributes: [...afterBlock.attributes.keys()],
        hasIdAttribute: true,
      },
      members: [],
    }));
  }
}

function addNewIdFinding(before, after, findings, counts) {
  const added = after.blocks.filter((block) => !before.ids.has(block.id));
  if (added.length === 0) return;
  const proportion = added.length / Math.max(after.blocks.length, 1);
  findings.push(finalise({
    rule: RULES.NEW_IDS,
    severity: RULES.NEW_IDS.severity,
    id: null,
    cause: proportion > 0.5
      ? `${added.length} of ${after.blocks.length} identifiers in the after document were not in the before `
        + 'document: more new blocks than carried-over ones, which is worth checking -- an editor minting '
        + 'its own identifiers looks exactly like this'
      : `${added.length} identifier(s) in the after document were not in the before document: blocks created `
        + 'after the capture, which is normal when the user kept typing',
    confidence: 'medium',
    evidence: added.slice(0, SAMPLE_LIMIT).map((block) => `${block.id} on ${block.tag}: "${block.preview}"`),
    locator: null,
    counterpart: null,
    members: [],
  }));
}

function locatorOf(block) {
  return {
    id: block.id,
    tag: block.tag,
    blockIndex: block.blockIndex,
    path: block.path,
    preview: block.preview,
    line: block.line,
    column: block.column,
    parentId: block.parentId,
    partType: block.partType,
  };
}

/** A stable identity for a finding, so a baseline file can name one. */
function findingKey(finding) {
  const parts = [
    finding.rule.code,
    finding.id || '',
    finding.locator ? finding.locator.path : '',
    finding.locator ? finding.locator.preview : '',
  ];
  return `${finding.rule.code}:${hash(parts.join('|'))}`;
}

function hash(value) {
  let h = 5381;
  for (let i = 0; i < value.length; i += 1) {
    h = ((h * 33) ^ value.charCodeAt(i)) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

function finalise(finding) {
  const complete = {
    rule: finding.rule.code,
    severity: finding.severity,
    title: finding.rule.title,
    meaning: finding.rule.meaning,
    id: finding.id,
    idRole: finding.idRole || 'block',
    cause: finding.cause,
    confidence: finding.confidence,
    evidence: finding.evidence.filter(Boolean),
    locator: finding.locator,
    counterpart: finding.counterpart,
    members: finding.members || [],
  };
  complete.key = findingKey({ ...finding, rule: finding.rule });
  return complete;
}

function buildReport(findings, counts, settings, signals) {
  const ordered = findings.slice().sort((a, b) => {
    const bySeverity = severityRank(a.severity) - severityRank(b.severity);
    if (bySeverity !== 0) return bySeverity;
    const aIndex = a.locator ? a.locator.blockIndex : 0;
    const bIndex = b.locator ? b.locator.blockIndex : 0;
    return aIndex - bIndex;
  });

  const summary = { error: 0, warning: 0, info: 0, notice: 0 };
  for (const finding of ordered) summary[finding.severity] += 1;

  return {
    schemaVersion: SCHEMA_VERSION,
    idAttribute: settings.idAttribute,
    ok: summary.error === 0,
    counts,
    summary,
    findings: ordered,
    signals: {
      beforeIdCount: signals.beforeIdCount,
      afterIdCount: signals.afterIdCount,
      lostTags: signals.lostTags,
    },
  };
}

export { locatorOf, shortText, describeNode };
