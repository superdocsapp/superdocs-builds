import { formatManagedValue, stringifyManagedValue } from "./profile";
import { fieldsForDocument } from "./registry";
import type {
  ManagedFieldPath,
  PolicyDocumentType,
  PolicyProfile,
  ValidationIssue,
  ValidationResult,
} from "./types";
import {
  ATTORNEY_REVIEW_DISCLAIMER,
  POLICY_DOCUMENT_TYPES,
} from "./types";

const MANAGED_FIELD_RE =
  /data-managed-field="([^"]+)"[^>]*>([^<]*)<\/span>/g;

export function validatePolicySet(
  profile: PolicyProfile,
  documents: Partial<Record<PolicyDocumentType, string>>,
): ValidationResult {
  const issues: ValidationIssue[] = [];

  for (const documentType of POLICY_DOCUMENT_TYPES) {
    const html = documents[documentType];
    if (html === undefined || html.trim() === "") {
      issues.push({
        code: "missing_required_document",
        message: `Missing required document: ${documentType}.`,
        documents: [documentType],
      });
      continue;
    }

    if (!html.includes(ATTORNEY_REVIEW_DISCLAIMER)) {
      issues.push({
        code: "missing_disclaimer",
        message: `Document "${documentType}" is missing the attorney-review disclaimer.`,
        documents: [documentType],
      });
    }

    const occurrences = parseManagedFields(html);
    const hasStructuredFacts = html.includes("data-managed-field=");
    for (const fieldPath of fieldsForDocument(documentType)) {
      const expected = formatManagedValue(profile, fieldPath);
      const structured = occurrences.get(fieldPath) ?? [];
      const found =
        structured.length > 0 || hasStructuredFacts
          ? structured
          : plainTextContainsManagedValue(html, fieldPath, expected)
            ? [expected]
            : [];

      if (found.length === 0 || found.some((value) => value !== expected)) {
        pushFieldMismatch(issues, documentType, fieldPath, expected, found);
      }
    }
  }

  const terms = documents.terms;
  const returnsDoc = documents.returns;
  const warrantyDoc = documents.warranty;

  if (terms && returnsDoc) {
    const termsWindow = firstReturnWindow(terms);
    const returnsWindow = firstReturnWindow(returnsDoc);
    if (
      termsWindow !== undefined &&
      returnsWindow !== undefined &&
      termsWindow !== returnsWindow
    ) {
      issues.push({
        code: "return_window_mismatch",
        message: `Terms return window (${termsWindow}) does not match Returns (${returnsWindow}).`,
        documents: ["terms", "returns"],
        fieldPath: "returns.windowDays",
      });
    }
  }

  if (terms && warrantyDoc) {
    const termsWarranty = firstField(terms, "warranty.durationMonths");
    const warrantyDuration = firstField(warrantyDoc, "warranty.durationMonths");
    if (
      termsWarranty !== undefined &&
      warrantyDuration !== undefined &&
      termsWarranty !== warrantyDuration
    ) {
      issues.push({
        code: "warranty_duration_mismatch",
        message: `Terms warranty duration (${termsWarranty}) does not match Warranty (${warrantyDuration}).`,
        documents: ["terms", "warranty"],
        fieldPath: "warranty.durationMonths",
      });
    }
  }

  const expectedWindow = stringifyManagedValue(
    "returns.windowDays",
    profile.returns.windowDays,
  );
  for (const documentType of ["terms", "returns"] as const) {
    const html = documents[documentType];
    if (!html) {
      continue;
    }
    const actual = firstReturnWindow(html);
    if (actual !== undefined && actual !== expectedWindow) {
      issues.push({
        code: "stale_managed_fact",
        message: `Document "${documentType}" still states return window ${actual} after the canonical profile moved to ${expectedWindow}.`,
        documents: [documentType],
        fieldPath: "returns.windowDays",
      });
    }
  }

  return { ok: issues.length === 0, issues };
}

export function validateReturnWindowTransition(
  previousValue: number,
  nextValue: number,
  documents: Partial<Record<PolicyDocumentType, string>>,
  affectedDocuments: readonly PolicyDocumentType[],
): ValidationResult {
  const issues: ValidationIssue[] = [];

  for (const documentType of affectedDocuments) {
    const html = documents[documentType];
    if (!html) {
      issues.push({
        code: "missing_required_document",
        message: `Missing required document: ${documentType}.`,
        documents: [documentType],
      });
      continue;
    }

    const values = returnWindowValues(html);
    if (!values.includes(nextValue)) {
      issues.push({
        code: "managed_transition_incomplete",
        message: `Document "${documentType}" does not contain the new ${nextValue}-day managed return window.`,
        documents: [documentType],
        fieldPath: "returns.windowDays",
      });
    }
    if (values.includes(previousValue)) {
      issues.push({
        code: "stale_managed_fact",
        message: `Document "${documentType}" still contains the stale ${previousValue}-day managed return window.`,
        documents: [documentType],
        fieldPath: "returns.windowDays",
      });
    }
  }

  return { ok: issues.length === 0, issues };
}

export function returnWindowValues(html: string): number[] {
  const text = htmlToPolicyText(html);
  const values = new Set<number>();
  const patterns = [
    /return window\s*\(days\)\s*:?\s*(\d+)/gi,
    /within\s+(\d+)\s+days?\b/gi,
    /\b(\d+)[ -]day\s+(?:return\s+)?window\b/gi,
  ];

  for (const pattern of patterns) {
    for (const match of text.matchAll(pattern)) {
      const value = Number(match[1]);
      if (Number.isInteger(value)) {
        values.add(value);
      }
    }
  }

  return [...values];
}

export function htmlToPolicyText(html: string): string {
  return decodeHtml(
    html
      .replace(/<br\s*\/?>/gi, " ")
      .replace(/<[^>]+>/g, " "),
  )
    .replace(/\s+/g, " ")
    .trim();
}

function parseManagedFields(html: string): Map<ManagedFieldPath, string[]> {
  const found = new Map<ManagedFieldPath, string[]>();
  const matcher = new RegExp(MANAGED_FIELD_RE.source, "g");
  let match: RegExpExecArray | null = matcher.exec(html);

  while (match) {
    const path = match[1] as ManagedFieldPath;
    const value = decodeHtml(match[2] ?? "");
    const existing = found.get(path) ?? [];
    existing.push(value);
    found.set(path, existing);
    match = matcher.exec(html);
  }

  return found;
}

function firstField(
  html: string,
  path: ManagedFieldPath,
): string | undefined {
  return parseManagedFields(html).get(path)?.[0];
}

function firstReturnWindow(html: string): string | undefined {
  return (
    firstField(html, "returns.windowDays") ??
    returnWindowValues(html)[0]?.toString()
  );
}

function plainTextContainsManagedValue(
  html: string,
  fieldPath: ManagedFieldPath,
  expected: string,
): boolean {
  const text = htmlToPolicyText(html);
  if (
    fieldPath === "store.minimumCustomerAge" ||
    fieldPath === "returns.windowDays" ||
    fieldPath === "returns.processingDays" ||
    fieldPath === "warranty.durationMonths"
  ) {
    return new RegExp(`(^|\\D)${escapeRegExp(expected)}(\\D|$)`).test(text);
  }
  return text.includes(expected);
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function pushFieldMismatch(
  issues: ValidationIssue[],
  documentType: PolicyDocumentType,
  fieldPath: ManagedFieldPath,
  expected: string,
  found: readonly string[],
): void {
  const actual = found[0];
  const detail =
    found.length === 0
      ? "the managed field is missing"
      : `found "${actual}" but expected "${expected}"`;

  if (fieldPath === "company.legalName") {
    issues.push({
      code: "company_name_mismatch",
      message: `Company name mismatch in "${documentType}": ${detail}.`,
      documents: [documentType],
      fieldPath,
    });
    return;
  }

  if (fieldPath === "company.supportEmail") {
    issues.push({
      code: "support_contact_mismatch",
      message: `Support contact mismatch in "${documentType}": ${detail}.`,
      documents: [documentType],
      fieldPath,
    });
    return;
  }

  if (fieldPath === "company.effectiveDate") {
    issues.push({
      code: "effective_date_mismatch",
      message: `Effective date mismatch in "${documentType}": ${detail}.`,
      documents: [documentType],
      fieldPath,
    });
    return;
  }

  if (fieldPath === "returns.windowDays") {
    issues.push({
      code: "stale_managed_fact",
      message: `Return window mismatch in "${documentType}": ${detail}.`,
      documents: [documentType],
      fieldPath,
    });
    return;
  }

  issues.push({
    code: "stale_managed_fact",
    message: `Managed fact "${fieldPath}" mismatch in "${documentType}": ${detail}.`,
    documents: [documentType],
    fieldPath,
  });
}

function decodeHtml(value: string): string {
  return value
    .replaceAll("&quot;", '"')
    .replaceAll("&gt;", ">")
    .replaceAll("&lt;", "<")
    .replaceAll("&amp;", "&");
}
