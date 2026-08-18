import {
  AlignmentType,
  convertInchesToTwip,
  Document,
  Footer,
  Header,
  HeadingLevel,
  Packer,
  Paragraph,
  TextRun,
} from "docx";

import {
  ATTORNEY_REVIEW_DISCLAIMER,
  POLICY_DOCUMENT_TYPES,
  renderPrivacy,
  renderReturns,
  renderTerms,
  renderWarranty,
  type PolicyDocumentType,
  type PolicyProfile,
} from "../domain";

import { parseRendererHtml, type DocumentBlock } from "./parse-html";
import { POLICY_DOCUMENT_FILENAMES, POLICY_DOCUMENT_TITLES } from "./spec";

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

const RENDERERS: Record<
  PolicyDocumentType,
  (profile: PolicyProfile) => string
> = {
  terms: renderTerms,
  privacy: renderPrivacy,
  warranty: renderWarranty,
  returns: renderReturns,
};

export type GeneratedPolicyDocument = {
  documentType: PolicyDocumentType;
  title: string;
  filename: string;
  contentType: typeof DOCX_MIME;
  bytes: Uint8Array;
};

export type GeneratedPolicySet = {
  documents: readonly GeneratedPolicyDocument[];
  byType: Record<PolicyDocumentType, GeneratedPolicyDocument>;
};

export async function generatePolicyDocuments(
  profile: PolicyProfile,
): Promise<GeneratedPolicySet> {
  const documents: GeneratedPolicyDocument[] = [];
  for (const documentType of POLICY_DOCUMENT_TYPES) {
    documents.push(await generatePolicyDocument(profile, documentType));
  }

  return {
    documents,
    byType: {
      terms: documents[0],
      privacy: documents[1],
      warranty: documents[2],
      returns: documents[3],
    },
  };
}

export async function generatePolicyDocument(
  profile: PolicyProfile,
  documentType: PolicyDocumentType,
): Promise<GeneratedPolicyDocument> {
  const title = POLICY_DOCUMENT_TITLES[documentType];
  const html = RENDERERS[documentType](profile);
  const blocks = parseRendererHtml(html);
  if (blocks.length === 0) {
    throw new Error(`Renderer produced no DOCX content for ${documentType}`);
  }

  const bytes = await packDocument({
    title,
    companyName: profile.company.legalName,
    blocks,
  });

  return {
    documentType,
    title,
    filename: POLICY_DOCUMENT_FILENAMES[documentType],
    contentType: DOCX_MIME,
    bytes,
  };
}

async function packDocument(input: {
  title: string;
  companyName: string;
  blocks: readonly DocumentBlock[];
}): Promise<Uint8Array> {
  const children: Paragraph[] = [];

  for (const block of input.blocks) {
    if (block.kind === "heading") {
      children.push(
        new Paragraph({
          heading:
            block.level === 1 ? HeadingLevel.HEADING_1 : HeadingLevel.HEADING_2,
          spacing: { after: 120 },
          children: [new TextRun({ text: block.text })],
        }),
      );
      continue;
    }

    if (block.kind === "fact") {
      children.push(
        new Paragraph({
          spacing: { after: 80 },
          children: [
            new TextRun({ text: `${block.label}: `, bold: true, size: 22 }),
            new TextRun({ text: block.value, size: 22 }),
          ],
        }),
      );
      continue;
    }

    children.push(
      new Paragraph({
        spacing: { after: 160 },
        children: [new TextRun({ text: block.text, size: 22 })],
      }),
    );
  }

  const document = new Document({
    title: input.title,
    creator: "PolicySet",
    description: `${input.title} generated from a PolicyProfile`,
    sections: [
      {
        properties: {
          page: {
            margin: {
              top: convertInchesToTwip(0.8),
              right: convertInchesToTwip(0.9),
              bottom: convertInchesToTwip(0.9),
              left: convertInchesToTwip(0.9),
            },
          },
        },
        headers: {
          default: new Header({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({
                    text: `${input.companyName} — ${input.title}`,
                    bold: true,
                    size: 18,
                  }),
                ],
              }),
            ],
          }),
        },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                alignment: AlignmentType.CENTER,
                children: [
                  new TextRun({
                    text: ATTORNEY_REVIEW_DISCLAIMER,
                    italics: true,
                    size: 18,
                  }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });

  const buffer = await Packer.toBuffer(document);
  return new Uint8Array(buffer);
}
