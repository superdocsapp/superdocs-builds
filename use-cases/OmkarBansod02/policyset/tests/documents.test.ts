import { describe, expect, it } from "vitest";

import {
  ATTORNEY_REVIEW_DISCLAIMER,
  NORTHSTAR_GOODS_PROFILE,
  POLICY_DOCUMENT_TYPES,
  formatManagedValue,
  fieldsForDocument,
} from "@/domain";
import { generatePolicyDocuments } from "@/documents";

import { docxFooterXml, docxPartXml, xmlPlainText } from "./docx-xml";

describe("generatePolicyDocuments", () => {
  it("generates exactly four Northstar DOCX documents", async () => {
    const generated = await generatePolicyDocuments(NORTHSTAR_GOODS_PROFILE);

    expect(generated.documents).toHaveLength(4);
    expect(generated.documents.map((document) => document.documentType)).toEqual(
      [...POLICY_DOCUMENT_TYPES],
    );
    expect(new Set(generated.documents.map((document) => document.filename)).size).toBe(
      4,
    );

    for (const document of generated.documents) {
      expect(document.bytes.byteLength).toBeGreaterThan(1000);
      expect(document.bytes[0]).toBe(0x50);
      expect(document.bytes[1]).toBe(0x4b);
      expect(document.title.length).toBeGreaterThan(0);
    }
  });

  it("places managed facts in the correct generated documents", async () => {
    const generated = await generatePolicyDocuments(NORTHSTAR_GOODS_PROFILE);
    const texts = Object.fromEntries(
      await Promise.all(
        generated.documents.map(async (document) => {
          const xml = await docxPartXml(document.bytes, "word/document.xml");
          return [document.documentType, xmlPlainText(xml)] as const;
        }),
      ),
    );

    for (const documentType of POLICY_DOCUMENT_TYPES) {
      const text = texts[documentType];
      expect(text).toContain("Northstar Goods LLC");
      expect(text).toContain("support@northstar.goods.test");
      expect(text).toContain("2026-01-15");

      for (const path of fieldsForDocument(documentType)) {
        expect(text).toContain(formatManagedValue(NORTHSTAR_GOODS_PROFILE, path));
      }
    }

    // Canonical values live in natural prose only: PolicySet no longer emits
    // a machine-style summary fact line duplicating them (see PROGRESS.md).
    for (const documentType of POLICY_DOCUMENT_TYPES) {
      expect(texts[documentType]).not.toContain("Return window (days)");
      expect(texts[documentType]).not.toContain("Warranty duration (months)");
    }

    expect(texts.privacy).toContain("90 days");
    expect(texts.terms).not.toContain("90 days");
    expect(texts.warranty).not.toContain("90 days");
    expect(texts.returns).not.toContain("90 days");
  });

  it("puts the disclaimer in a real Word footer, not the body", async () => {
    const generated = await generatePolicyDocuments(NORTHSTAR_GOODS_PROFILE);

    for (const document of generated.documents) {
      const footers = await docxFooterXml(document.bytes);
      expect(footers.some((xml) => xmlPlainText(xml).includes(ATTORNEY_REVIEW_DISCLAIMER))).toBe(
        true,
      );

      const body = xmlPlainText(
        await docxPartXml(document.bytes, "word/document.xml"),
      );
      expect(body).not.toContain(ATTORNEY_REVIEW_DISCLAIMER);
    }
  });
});
