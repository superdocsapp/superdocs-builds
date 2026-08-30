// @ts-check
/**
 * Generates the two fixture .docx files this project's tests and demo run
 * against. Uses the `docx` (docx-js) package — real OOXML output, not a
 * hand-rolled stub.
 *
 * Design: every PRISM DELTA category gets exactly one deliberate, known
 * change between v1 -> v2, plus one paragraph left byte-for-byte identical
 * as a true-negative check (the system must NOT flag it).
 *
 *   unchanged   : intro/parties paragraph            -> no change expected
 *   numeric     : fee paragraph ($ amount + day count) -> 'numeric', material
 *   date        : term paragraph (start date)          -> 'date', material
 *   semantic    : confidentiality paragraph (obligation language + new
 *                 indemnification clause)               -> 'semantic', review-required
 *   formatting  : notices paragraph (same text, now bold) -> 'formatting', cosmetic
 *   structural  : new "Governing Law" section in v2 only -> 'structural-add', review-required
 */
import { Document, Paragraph, TextRun, HeadingLevel, Packer } from 'docx';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function buildDoc({ feeText, termText, confidentialityText, noticesBold, includeGoverningLaw }) {
  const children = [
    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun('SERVICES AGREEMENT')] }),
    new Paragraph({
      children: [
        new TextRun(
          'This Services Agreement (the "Agreement") is entered into between Acme Consulting LLC ("Contractor") and Northwind Retail Inc. ("Company").',
        ),
      ],
    }),
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('1. Fees')] }),
    new Paragraph({ children: [new TextRun(feeText)] }),
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('2. Term')] }),
    new Paragraph({ children: [new TextRun(termText)] }),
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('3. Confidentiality')] }),
    new Paragraph({ children: [new TextRun(confidentialityText)] }),
    new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('4. Notices')] }),
    new Paragraph({
      children: [
        new TextRun({
          text: 'All notices under this Agreement must be delivered in writing to the addresses set forth above.',
          bold: noticesBold,
        }),
      ],
    }),
  ];

  if (includeGoverningLaw) {
    children.push(
      new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun('5. Governing Law')] }),
      new Paragraph({
        children: [new TextRun('This Agreement shall be governed by the laws of the State of Delaware.')],
      }),
    );
  }

  return new Document({ sections: [{ children }] });
}

const v1 = buildDoc({
  feeText: 'The total contract price is $50,000, payable within 30 days of invoice.',
  termText: 'This Agreement commences on January 1, 2026 and continues for twelve (12) months.',
  confidentialityText:
    'The Contractor shall use reasonable efforts to protect Confidential Information disclosed by the Company.',
  noticesBold: false,
  includeGoverningLaw: false,
});

const v2 = buildDoc({
  feeText: 'The total contract price is $65,000, payable within 15 days of invoice.',
  termText: 'This Agreement commences on March 1, 2026 and continues for twelve (12) months.',
  confidentialityText:
    'The Contractor shall use best efforts to protect Confidential Information disclosed by the Company and shall indemnify the Company for any breach.',
  noticesBold: true,
  includeGoverningLaw: true,
});

const [bufV1, bufV2] = await Promise.all([Packer.toBuffer(v1), Packer.toBuffer(v2)]);
await writeFile(path.join(__dirname, 'contract-v1.docx'), bufV1);
await writeFile(path.join(__dirname, 'contract-v2.docx'), bufV2);
console.log('Wrote fixtures/contract-v1.docx and fixtures/contract-v2.docx');
