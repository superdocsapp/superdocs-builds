import type { PolicyDocumentType } from "../domain";

export const POLICY_DOCUMENT_TITLES = {
  terms: "Terms of Service",
  privacy: "Privacy Policy",
  warranty: "Warranty Policy",
  returns: "Returns Policy",
} as const satisfies Record<PolicyDocumentType, string>;

export const POLICY_DOCUMENT_FILENAMES = {
  terms: "terms-of-service.docx",
  privacy: "privacy-policy.docx",
  warranty: "warranty-policy.docx",
  returns: "returns-policy.docx",
} as const satisfies Record<PolicyDocumentType, string>;
