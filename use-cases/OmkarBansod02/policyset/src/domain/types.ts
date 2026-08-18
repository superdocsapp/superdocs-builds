export const POLICY_DOCUMENT_TYPES = [
  "terms",
  "privacy",
  "warranty",
  "returns",
] as const;

export type PolicyDocumentType = (typeof POLICY_DOCUMENT_TYPES)[number];

export const ATTORNEY_REVIEW_DISCLAIMER =
  "drafted for attorney review, not legal advice";

export type ChangeSetStatus =
  | "pending"
  | "proposed"
  | "approved"
  | "rejected"
  | "failed";

export type MailingAddress = {
  line1: string;
  city: string;
  region: string;
  postalCode: string;
  country: string;
};

export type ReturnShippingPayer = "customer" | "merchant";

export type PolicyProfile = {
  company: {
    legalName: string;
    website: string;
    supportEmail: string;
    mailingAddress: MailingAddress;
    effectiveDate: string;
    governingJurisdiction: string;
  };
  store: {
    minimumCustomerAge: number;
    shippingRegions: readonly string[];
    paymentProcessor: string;
  };
  returns: {
    windowDays: number;
    eligibleCondition: string;
    returnShippingPayer: ReturnShippingPayer;
    refundMethod: string;
    processingDays: number;
    finalSaleExceptions: readonly string[];
  };
  warranty: {
    durationMonths: number;
    coveredDefects: string;
    exclusions: string;
    claimMethod: string;
  };
  privacy: {
    collectedDataCategories: readonly string[];
    purposes: readonly string[];
    processors: readonly string[];
    analyticsEnabled: boolean;
    marketingEnabled: boolean;
    retentionSummary: string;
  };
};

export type ChangeSet = {
  id: string;
  fieldPath: ManagedFieldPath;
  previousValue: unknown;
  nextValue: unknown;
  affectedDocuments: readonly PolicyDocumentType[];
  status: ChangeSetStatus;
};

export const DEPENDENCY_REGISTRY = {
  "company.legalName": ["terms", "privacy", "warranty", "returns"],
  "company.website": ["terms", "privacy", "warranty", "returns"],
  "company.supportEmail": ["terms", "privacy", "warranty", "returns"],
  "company.mailingAddress": ["terms", "privacy", "warranty", "returns"],
  "company.effectiveDate": ["terms", "privacy", "warranty", "returns"],
  "company.governingJurisdiction": ["terms", "privacy", "warranty", "returns"],
  "store.minimumCustomerAge": ["terms"],
  "store.shippingRegions": ["terms", "returns"],
  "store.paymentProcessor": ["terms", "privacy"],
  "returns.windowDays": ["terms", "returns"],
  "returns.eligibleCondition": ["terms", "returns"],
  "returns.returnShippingPayer": ["returns"],
  "returns.refundMethod": ["returns"],
  "returns.processingDays": ["returns"],
  "returns.finalSaleExceptions": ["returns"],
  "warranty.durationMonths": ["terms", "warranty"],
  "warranty.coveredDefects": ["warranty"],
  "warranty.exclusions": ["warranty"],
  "warranty.claimMethod": ["warranty"],
  "privacy.collectedDataCategories": ["privacy"],
  "privacy.purposes": ["privacy"],
  "privacy.processors": ["privacy"],
  "privacy.analyticsEnabled": ["privacy"],
  "privacy.marketingEnabled": ["privacy"],
  "privacy.retentionSummary": ["privacy"],
} as const satisfies Record<string, readonly PolicyDocumentType[]>;

export type ManagedFieldPath = keyof typeof DEPENDENCY_REGISTRY;

export const MANAGED_FIELD_PATHS = Object.freeze(
  Object.keys(DEPENDENCY_REGISTRY),
) as readonly ManagedFieldPath[];

export type PolicyDocumentSet = Record<PolicyDocumentType, string>;

export type ValidationIssueCode =
  | "missing_required_document"
  | "missing_disclaimer"
  | "company_name_mismatch"
  | "support_contact_mismatch"
  | "effective_date_mismatch"
  | "return_window_mismatch"
  | "warranty_duration_mismatch"
  | "stale_managed_fact"
  | "managed_transition_incomplete"
  | "untouched_document_changed";

export type ValidationIssue = {
  code: ValidationIssueCode;
  message: string;
  documents?: PolicyDocumentType[];
  fieldPath?: ManagedFieldPath;
};

export type ValidationResult = {
  ok: boolean;
  issues: ValidationIssue[];
};
