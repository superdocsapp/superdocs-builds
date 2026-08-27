/**
 * The rule table. Every finding this package can produce is declared here, with
 * the severity it carries by default and the one-line statement of what it means.
 *
 * The point of the table is that a report never says "something went wrong". It
 * says which transformation happened, and a rule code is the machine-readable
 * half of that sentence.
 */

export const SEVERITIES = ['error', 'warning', 'info', 'notice'];

export function severityRank(severity) {
  const rank = SEVERITIES.indexOf(severity);
  return rank === -1 ? SEVERITIES.length : rank;
}

export function atLeastAsSevere(severity, threshold) {
  return severityRank(severity) <= severityRank(threshold);
}

/** @type {Record<string, { code: string, severity: string, title: string, meaning: string }>} */
export const RULES = {
  IDS_REGENERATED: {
    code: 'IDS_REGENERATED',
    severity: 'error',
    title: 'Identifiers regenerated wholesale',
    meaning:
      'Not one identifier survived, yet the after document carries identifiers of its own. '
      + 'The editor set its own content instead of applying the document_sync HTML, so every '
      + 'change batch the model sends will miss.',
  },
  ALL_IDS_STRIPPED: {
    code: 'ALL_IDS_STRIPPED',
    severity: 'error',
    title: 'Every identifier stripped',
    meaning:
      'The after document carries no identifiers at all. Targeted editing is impossible: the '
      + 'next turn can only be a whole-document rewrite.',
  },
  LOST_ATTRIBUTE_STRIPPED: {
    code: 'LOST_ATTRIBUTE_STRIPPED',
    severity: 'error',
    title: 'Identifier stripped from a surviving block',
    meaning:
      'The block is still there, with the same tag and the same text, and only the identifier '
      + 'is missing. Something on the path filters attributes.',
  },
  LOST_NODE_REBUILT: {
    code: 'LOST_NODE_REBUILT',
    severity: 'error',
    title: 'Block rebuilt as a different element',
    meaning:
      'The text survived under a different tag. The node was reconstructed by a different '
      + 'document model rather than edited in place, and the identifier did not come with it.',
  },
  LOST_MARKDOWN_HOP: {
    code: 'LOST_MARKDOWN_HOP',
    severity: 'error',
    title: 'Block passed through a markdown or plain-text hop',
    meaning:
      'The block came back with no attributes at all, in a region where nothing has attributes. '
      + 'Something in the middle of the pipeline converted the HTML to text and back.',
  },
  LOST_BLOCK_REMOVED: {
    code: 'LOST_BLOCK_REMOVED',
    severity: 'error',
    title: 'Block absent from the after document',
    meaning:
      'No node in the after document carries this text. The block was deleted, replaced '
      + 'wholesale, or never rendered by the integration.',
  },
  LOST_SUBTREE: {
    code: 'LOST_SUBTREE',
    severity: 'error',
    title: 'A whole subtree lost identity',
    meaning:
      'Every identified block under one surviving ancestor lost its identifier the same way. '
      + 'One transformation is responsible for all of them.',
  },
  DUPLICATE_ID: {
    code: 'DUPLICATE_ID',
    severity: 'error',
    title: 'Same identifier on more than one block',
    meaning:
      'A change batch targeting this identifier is ambiguous: the edit can land on either node. '
      + 'Usually a copy-paste, a split block, or a node cloned by the editor.',
  },
  DUPLICATE_ID_IN_SOURCE: {
    code: 'DUPLICATE_ID_IN_SOURCE',
    severity: 'warning',
    title: 'Duplicate identifier in the before document',
    meaning:
      'The input to the round trip is already ambiguous, so nothing downstream can be trusted '
      + 'to resolve it. Check where the before HTML was captured.',
  },
  DATA_ATTRIBUTE_DROPPED: {
    code: 'DATA_ATTRIBUTE_DROPPED',
    severity: 'error',
    title: 'Block kept its identifier but lost another data attribute',
    meaning:
      'Diagram sources, equation sources, citation fields and out-of-flow part markers ride on '
      + 'data attributes and have the same silent failure mode as the identifier itself.',
  },
  PART_OMITTED: {
    code: 'PART_OMITTED',
    severity: 'info',
    title: 'Out-of-flow part not present in the after document',
    meaning:
      'Headers, footers, footnote bodies and comments may legitimately be absent from an editor '
      + 'view, and their absence never deletes them. Reported so it is visible, not as a failure.',
  },
  BLOCK_MOVED: {
    code: 'BLOCK_MOVED',
    severity: 'info',
    title: 'Block moved with its identity intact',
    meaning: 'Reordering, not loss. Reported separately so it is never mistaken for one.',
  },
  CONTENT_CHANGED: {
    code: 'CONTENT_CHANGED',
    severity: 'notice',
    title: 'Block kept its identifier and changed its text',
    meaning: 'Ordinary editing. Off by default; switch it on to audit what a round trip rewrote.',
  },
  NEW_IDS: {
    code: 'NEW_IDS',
    severity: 'info',
    title: 'Identifiers in the after document that were not in the before document',
    meaning:
      'Blocks created after the capture. Normal when the user typed; worth a look when the count '
      + 'is large, because it can mean the editor is minting its own identifiers.',
  },
  NO_IDS_IN_SOURCE: {
    code: 'NO_IDS_IN_SOURCE',
    severity: 'error',
    title: 'The before document carries no identifiers',
    meaning:
      'There is nothing to validate. Either the capture is wrong, or the loss happened before '
      + 'the point where the before HTML was taken.',
  },
};

/**
 * Data attributes whose loss breaks something specific, rather than merely being
 * unexpected. Anything else that goes missing is reported as a warning.
 */
export const CRITICAL_DATA_ATTRIBUTES = new Map([
  ['data-part-type', 'the block stops being recognised as a header, footer, footnote or comment'],
  ['data-diagram-source', 'the diagram degrades to an empty block on the next edit cycle'],
  ['data-diagram-type', 'the diagram can no longer be re-rendered from its source'],
  ['data-mermaid', 'the diagram source is gone and cannot be recovered from the rendered SVG'],
  ['data-latex', 'the equation degrades to rendered output with no recoverable source'],
  ['data-equation', 'the equation source is gone'],
  ['data-citation-id', 'the citation stops resolving and will not survive export'],
  ['data-citation', 'the citation stops resolving and will not survive export'],
  ['data-footnote-id', 'the footnote reference loses its target'],
]);
