import { ClientBatchRecord } from '../types';

/**
 * Build the finished, human-reviewed document text for export.
 *
 * The whole point of the SuperDocs human gate is that a CPA approves edits
 * before the document is finalized -- so "export the finished file" must return
 * a document that CONTAINS the approved edits. This builder folds every
 * APPROVED diff's proposed text into the base letter/organizer content, and
 * excludes rejected and still-pending diffs. It is the single source of truth
 * for what the exported file contains, and is unit-tested against approved /
 * rejected / pending diff mixes.
 */
export function buildExportContent(
  client: ClientBatchRecord,
  exportType: 'letter' | 'organizer' | string
): string {
  let baseContent = '';
  if (exportType === 'letter') {
    baseContent =
      `${client.yearEndLetter.greeting}\n\n${client.yearEndLetter.overview}\n\n` +
      client.yearEndLetter.personalizedLawParagraphs
        .map((p) => `${p.lawTitle}\nImpact: ${p.estimatedImpact}\nAction: ${p.actionItem}`)
        .join('\n\n') +
      `\n\n${client.yearEndLetter.filingDeadlineNotice}\n\n${client.yearEndLetter.closing}`;
  } else {
    baseContent =
      `TAX ORGANIZER: ${client.clientName}\nSegment: ${client.segment.toUpperCase()}\n\n` +
      client.organizer
        .map(
          (sec) =>
            `=== ${sec.sectionTitle} ===\n` +
            sec.requiredDocuments
              .map((d) => `[${d.status.toUpperCase()}] ${d.docName} (Source: ${d.sourceCitation})`)
              .join('\n')
        )
        .join('\n\n');
  }

  // Prefer the merged appliedEdits on the letter (populated at approval time),
  // so export matches exactly what the preview/copy/print show -- one source of
  // truth. Fall back to deriving from approved diffs for older records that
  // predate the merge.
  const merged = client.yearEndLetter.appliedEdits && client.yearEndLetter.appliedEdits.length > 0
    ? client.yearEndLetter.appliedEdits.map((e, i) => `${i + 1}. ${e}`)
    : client.diffs
        .filter((d) => d.status === 'approved')
        .map((d, i) => `${i + 1}. [${(d.changeType || 'modification').toUpperCase()}] ${d.locationLabel}\n${d.proposedText}`);

  if (merged.length === 0) return baseContent;

  return (
    baseContent +
    `\n\n===== APPROVED EDITS (applied via SuperDocs human-gate review) =====\n\n` +
    merged.join('\n\n')
  );
}
