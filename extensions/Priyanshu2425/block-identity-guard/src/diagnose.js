/**
 * The diagnosis layer.
 *
 * The set difference tells you an identifier is missing. This file is what turns
 * that into a sentence a reader can act on: which transformation dropped it, how
 * confident that reading is, and the evidence the reading rests on. Every cause
 * names a transformation ("an attribute allowlist stripped it"), never a symptom
 * ("id mismatch").
 */

import { RULES } from './rules.js';
import { describeNode } from './match.js';

/** Tags a markdown round trip can express. Anything else does not survive one. */
const MARKDOWN_TAGS = new Set([
  'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote',
  'pre', 'code', 'em', 'i', 'strong', 'b', 'a', 'hr', 'br', 'img',
  'table', 'thead', 'tbody', 'tr', 'td', 'th', 'del', 'input',
]);

const UUID_SHAPE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Facts about the pair of documents that individual rules read. */
export function computeSignals(before, after, idAttribute) {
  const afterDataAttributes = countDataAttributes(after, idAttribute);
  const beforeDataAttributes = countDataAttributes(before, idAttribute);
  const lostTags = [...before.tagNames].filter((tag) => !after.tagNames.has(tag));
  const nonMarkdownTagsGone = lostTags.filter((tag) => !MARKDOWN_TAGS.has(tag));

  return {
    idAttribute,
    beforeIdCount: before.blocks.length,
    afterIdCount: after.blocks.length,
    beforeDataAttributes,
    afterDataAttributes,
    /** True when the after document kept identifiers somewhere, so a loss is localised. */
    afterKeptSomeIds: after.blocks.length > 0,
    lostTags,
    /** Tags that only a rich document model can express, and that are now gone. */
    nonMarkdownTagsGone,
    afterVocabularyIsMarkdownOnly: [...after.tagNames].every((tag) => MARKDOWN_TAGS.has(tag)),
    beforeIdsLookGenerated: before.blocks.some((block) => UUID_SHAPE.test(block.id)),
    afterIdsLookGenerated: after.blocks.some((block) => UUID_SHAPE.test(block.id)),
  };
}

function countDataAttributes(document, idAttribute) {
  let count = 0;
  for (const [name, times] of document.attributeNames) {
    if (name === idAttribute) continue;
    if (name.startsWith('data-')) count += times;
  }
  return count;
}

function hasAnyAttribute(node) {
  return node.attributes.size > 0;
}

function subtreeHasAttribute(node) {
  for (const entry of node.contents) {
    if (typeof entry === 'string') continue;
    if (hasAnyAttribute(entry)) return true;
    if (subtreeHasAttribute(entry)) return true;
  }
  return false;
}

/**
 * True when this node, everything under it, and the blocks beside it all came
 * back with no attributes at all.
 *
 * Deliberately looks sideways rather than upwards: after a markdown hop the
 * surviving wrapper still carries its own attributes, so asking whether the
 * *parent* is clean answers the wrong question. What identifies a hop is a run
 * of neighbours that are all equally bare.
 */
function attributeFreeNeighbourhood(node) {
  if (hasAnyAttribute(node)) return false;
  if (subtreeHasAttribute(node)) return false;

  const siblings = node.parent ? node.parent.children.filter((child) => child !== node) : [];
  if (siblings.length === 0) return true;
  const bare = siblings.filter((sibling) => !hasAnyAttribute(sibling));
  return bare.length >= Math.ceil(siblings.length / 2);
}

/**
 * @param {object} block a before-side block whose identifier is missing after
 * @param {{ node: object|null, how: string, unique: boolean, similarity: number }} match
 * @param {{ after: object, signals: object, idAttribute: string }} context
 */
export function diagnoseLostBlock(block, match, context) {
  const { after, signals, idAttribute } = context;
  const evidence = [];
  const anchor = block.parentId
    ? `nearest surviving ancestor ${block.parentId}`
    : 'no surviving ancestor carries an identifier';

  if (!match.node) {
    evidence.push('no node in the after document carries this text, or anything close to it');
    evidence.push(anchor);
    return {
      rule: RULES.LOST_BLOCK_REMOVED,
      cause:
        'the block is not in the after document at all: it was deleted, replaced wholesale, '
        + 'or the integration never rendered it',
      confidence: block.text.length >= 3 ? 'high' : 'low',
      evidence,
      counterpart: null,
    };
  }

  const counterpart = describeNode(match.node, after, idAttribute);
  const tagChanged = match.node.tag !== block.tag;
  const attributeNames = [...match.node.attributes.keys()];
  const keptDataAttributes = attributeNames.filter((name) => name.startsWith('data-'));
  const keptOtherAttributes = attributeNames.filter((name) => !name.startsWith('data-'));

  if (match.how === 'similar-text') {
    evidence.push(`text also changed (${Math.round(match.similarity * 100)}% of words in common)`);
  }
  if (!match.unique && match.how !== 'similar-text') {
    evidence.push('this text is not unique in the after document, so the counterpart is the best match rather than the only one');
  }
  evidence.push(anchor);

  if (tagChanged) {
    const collapse = `from ${block.tag} to ${match.node.tag}`;
    if (attributeFreeNeighbourhood(match.node) && signals.afterVocabularyIsMarkdownOnly) {
      return {
        rule: RULES.LOST_MARKDOWN_HOP,
        cause:
          `the node came back rewritten ${collapse} with every attribute gone, in a region where nothing `
          + 'has attributes: a markdown or plain-text hop in the middle of the pipeline',
        confidence: 'medium',
        evidence: withRegionEvidence(evidence, signals),
        counterpart,
      };
    }
    return {
      rule: RULES.LOST_NODE_REBUILT,
      cause:
        `the node was rebuilt as ${collapse} by a different document model -- a serialisation `
        + 'round trip, not an edit, and the identifier was not carried across',
      confidence: match.how === 'similar-text' ? 'medium' : 'high',
      evidence: evidence.concat(
        keptDataAttributes.length > 0
          ? `the rebuilt node still carries ${keptDataAttributes.join(', ')}`
          : 'the rebuilt node carries no data attributes',
      ),
      counterpart,
    };
  }

  if (keptDataAttributes.length > 0) {
    return {
      rule: RULES.LOST_ATTRIBUTE_STRIPPED,
      cause:
        `the tag and text are unchanged and the node still carries ${keptDataAttributes.join(', ')}, `
        + `so ${idAttribute} specifically was filtered out -- an attribute allowlist that names the `
        + 'attributes it keeps, or an editor schema that only stores attributes it knows about',
      confidence: 'high',
      evidence,
      counterpart,
    };
  }

  if (keptOtherAttributes.length > 0) {
    return {
      rule: RULES.LOST_ATTRIBUTE_STRIPPED,
      cause:
        `the tag and text are unchanged and the node kept ${keptOtherAttributes.join(', ')} but no `
        + 'data attributes, which is what a sanitiser or editor schema with an attribute allowlist '
        + 'does: known attributes through, unknown attributes dropped',
      confidence: 'high',
      evidence,
      counterpart,
    };
  }

  if (attributeFreeNeighbourhood(match.node) && signals.nonMarkdownTagsGone.length > 0) {
    return {
      rule: RULES.LOST_MARKDOWN_HOP,
      cause:
        'the node kept its tag and text but came back with no attributes at all, and tags that only '
        + `a rich document model can express are gone from the whole document (${signals.nonMarkdownTagsGone.join(', ')}): `
        + 'a markdown or plain-text hop in the middle of the pipeline',
      confidence: 'medium',
      evidence: withRegionEvidence(evidence, signals),
      counterpart,
    };
  }

  return {
    rule: RULES.LOST_ATTRIBUTE_STRIPPED,
    cause:
      'the tag and text are unchanged and every attribute is gone, which is a sanitiser or editor '
      + 'schema stripping all unknown attributes rather than one filtered attribute',
    confidence: 'medium',
    evidence,
    counterpart,
  };
}

function withRegionEvidence(evidence, signals) {
  if (signals.afterKeptSomeIds) {
    return evidence.concat(
      `the after document still carries ${signals.afterIdCount} identifier(s) elsewhere, so this is a `
      + 'localised hop rather than a whole-document one',
    );
  }
  return evidence;
}

export { MARKDOWN_TAGS, attributeFreeNeighbourhood };
