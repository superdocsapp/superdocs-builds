import { err, ok, type Result } from "./result";
import type {
  MailingAddress,
  ManagedFieldPath,
  PolicyProfile,
  ReturnShippingPayer,
} from "./types";

export function clonePolicyProfile(profile: PolicyProfile): PolicyProfile {
  return structuredClone(profile);
}

export function formatMailingAddress(address: MailingAddress): string {
  return `${address.line1}, ${address.city}, ${address.region} ${address.postalCode}, ${address.country}`;
}

export function getManagedFieldValue(
  profile: PolicyProfile,
  path: ManagedFieldPath,
): unknown {
  switch (path) {
    case "company.legalName":
      return profile.company.legalName;
    case "company.website":
      return profile.company.website;
    case "company.supportEmail":
      return profile.company.supportEmail;
    case "company.mailingAddress":
      return profile.company.mailingAddress;
    case "company.effectiveDate":
      return profile.company.effectiveDate;
    case "company.governingJurisdiction":
      return profile.company.governingJurisdiction;
    case "store.minimumCustomerAge":
      return profile.store.minimumCustomerAge;
    case "store.shippingRegions":
      return profile.store.shippingRegions;
    case "store.paymentProcessor":
      return profile.store.paymentProcessor;
    case "returns.windowDays":
      return profile.returns.windowDays;
    case "returns.eligibleCondition":
      return profile.returns.eligibleCondition;
    case "returns.returnShippingPayer":
      return profile.returns.returnShippingPayer;
    case "returns.refundMethod":
      return profile.returns.refundMethod;
    case "returns.processingDays":
      return profile.returns.processingDays;
    case "returns.finalSaleExceptions":
      return profile.returns.finalSaleExceptions;
    case "warranty.durationMonths":
      return profile.warranty.durationMonths;
    case "warranty.coveredDefects":
      return profile.warranty.coveredDefects;
    case "warranty.exclusions":
      return profile.warranty.exclusions;
    case "warranty.claimMethod":
      return profile.warranty.claimMethod;
    case "privacy.collectedDataCategories":
      return profile.privacy.collectedDataCategories;
    case "privacy.purposes":
      return profile.privacy.purposes;
    case "privacy.processors":
      return profile.privacy.processors;
    case "privacy.analyticsEnabled":
      return profile.privacy.analyticsEnabled;
    case "privacy.marketingEnabled":
      return profile.privacy.marketingEnabled;
    case "privacy.retentionSummary":
      return profile.privacy.retentionSummary;
  }
}

export function formatManagedValue(
  profile: PolicyProfile,
  path: ManagedFieldPath,
): string {
  return stringifyManagedValue(path, getManagedFieldValue(profile, path));
}

export function stringifyManagedValue(
  path: ManagedFieldPath,
  value: unknown,
): string {
  switch (path) {
    case "company.mailingAddress":
      return formatMailingAddress(value as MailingAddress);
    case "store.shippingRegions":
    case "returns.finalSaleExceptions":
    case "privacy.collectedDataCategories":
    case "privacy.purposes":
    case "privacy.processors":
      return (value as readonly string[]).join(", ");
    case "privacy.analyticsEnabled":
    case "privacy.marketingEnabled":
      return (value as boolean) ? "yes" : "no";
    default:
      return String(value);
  }
}

export function valuesEqual(left: unknown, right: unknown): boolean {
  return stableSerialize(left) === stableSerialize(right);
}

export function parseManagedFieldValue(
  path: ManagedFieldPath,
  value: unknown,
): Result<unknown> {
  switch (path) {
    case "company.legalName":
    case "company.website":
    case "company.supportEmail":
    case "company.effectiveDate":
    case "company.governingJurisdiction":
    case "store.paymentProcessor":
    case "returns.eligibleCondition":
    case "returns.refundMethod":
    case "warranty.coveredDefects":
    case "warranty.exclusions":
    case "warranty.claimMethod":
    case "privacy.retentionSummary":
      return requireNonEmptyString(value, path);
    case "company.mailingAddress":
      return requireMailingAddress(value);
    case "store.minimumCustomerAge":
      return requirePositiveInteger(value, path);
    case "returns.windowDays":
    case "returns.processingDays":
    case "warranty.durationMonths":
      return requirePositiveInteger(value, path);
    case "store.shippingRegions":
    case "privacy.collectedDataCategories":
    case "privacy.purposes":
    case "privacy.processors":
      return requireNonEmptyStringArray(value, path);
    case "returns.finalSaleExceptions":
      return requireStringArray(value, path);
    case "returns.returnShippingPayer":
      return requireReturnShippingPayer(value);
    case "privacy.analyticsEnabled":
    case "privacy.marketingEnabled":
      return requireBoolean(value, path);
  }
}

export function applyManagedField(
  profile: PolicyProfile,
  path: ManagedFieldPath,
  value: unknown,
): PolicyProfile {
  const next = clonePolicyProfile(profile);

  switch (path) {
    case "company.legalName":
      next.company.legalName = value as string;
      break;
    case "company.website":
      next.company.website = value as string;
      break;
    case "company.supportEmail":
      next.company.supportEmail = value as string;
      break;
    case "company.mailingAddress":
      next.company.mailingAddress = value as MailingAddress;
      break;
    case "company.effectiveDate":
      next.company.effectiveDate = value as string;
      break;
    case "company.governingJurisdiction":
      next.company.governingJurisdiction = value as string;
      break;
    case "store.minimumCustomerAge":
      next.store.minimumCustomerAge = value as number;
      break;
    case "store.shippingRegions":
      next.store.shippingRegions = value as string[];
      break;
    case "store.paymentProcessor":
      next.store.paymentProcessor = value as string;
      break;
    case "returns.windowDays":
      next.returns.windowDays = value as number;
      break;
    case "returns.eligibleCondition":
      next.returns.eligibleCondition = value as string;
      break;
    case "returns.returnShippingPayer":
      next.returns.returnShippingPayer = value as ReturnShippingPayer;
      break;
    case "returns.refundMethod":
      next.returns.refundMethod = value as string;
      break;
    case "returns.processingDays":
      next.returns.processingDays = value as number;
      break;
    case "returns.finalSaleExceptions":
      next.returns.finalSaleExceptions = value as string[];
      break;
    case "warranty.durationMonths":
      next.warranty.durationMonths = value as number;
      break;
    case "warranty.coveredDefects":
      next.warranty.coveredDefects = value as string;
      break;
    case "warranty.exclusions":
      next.warranty.exclusions = value as string;
      break;
    case "warranty.claimMethod":
      next.warranty.claimMethod = value as string;
      break;
    case "privacy.collectedDataCategories":
      next.privacy.collectedDataCategories = value as string[];
      break;
    case "privacy.purposes":
      next.privacy.purposes = value as string[];
      break;
    case "privacy.processors":
      next.privacy.processors = value as string[];
      break;
    case "privacy.analyticsEnabled":
      next.privacy.analyticsEnabled = value as boolean;
      break;
    case "privacy.marketingEnabled":
      next.privacy.marketingEnabled = value as boolean;
      break;
    case "privacy.retentionSummary":
      next.privacy.retentionSummary = value as string;
      break;
  }

  return next;
}

function stableSerialize(value: unknown): string {
  return JSON.stringify(value, (_, nested) => {
    if (nested && typeof nested === "object" && !Array.isArray(nested)) {
      return Object.fromEntries(
        Object.entries(nested as Record<string, unknown>).sort(([a], [b]) =>
          a.localeCompare(b),
        ),
      );
    }
    return nested as unknown;
  });
}

function requireNonEmptyString(
  value: unknown,
  path: ManagedFieldPath,
): Result<string> {
  if (typeof value !== "string" || value.trim() === "") {
    return err(
      "INVALID_FIELD_VALUE",
      `${path} must be a non-empty string.`,
    );
  }
  return ok(value);
}

function requirePositiveInteger(
  value: unknown,
  path: ManagedFieldPath,
): Result<number> {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    return err(
      "INVALID_FIELD_VALUE",
      `${path} must be a positive integer.`,
    );
  }
  return ok(value);
}

function requireBoolean(
  value: unknown,
  path: ManagedFieldPath,
): Result<boolean> {
  if (typeof value !== "boolean") {
    return err("INVALID_FIELD_VALUE", `${path} must be a boolean.`);
  }
  return ok(value);
}

function requireStringArray(
  value: unknown,
  path: ManagedFieldPath,
): Result<string[]> {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || item.trim() === "")
  ) {
    return err(
      "INVALID_FIELD_VALUE",
      `${path} must be an array of non-empty strings.`,
    );
  }
  return ok([...value]);
}

function requireNonEmptyStringArray(
  value: unknown,
  path: ManagedFieldPath,
): Result<string[]> {
  const parsed = requireStringArray(value, path);
  if (!parsed.ok) {
    return parsed;
  }
  if (parsed.value.length === 0) {
    return err(
      "INVALID_FIELD_VALUE",
      `${path} must contain at least one value.`,
    );
  }
  return parsed;
}

function requireReturnShippingPayer(
  value: unknown,
): Result<ReturnShippingPayer> {
  if (value !== "customer" && value !== "merchant") {
    return err(
      "INVALID_FIELD_VALUE",
      'returns.returnShippingPayer must be "customer" or "merchant".',
    );
  }
  return ok(value);
}

function requireMailingAddress(value: unknown): Result<MailingAddress> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return err(
      "INVALID_FIELD_VALUE",
      "company.mailingAddress must be an address object.",
    );
  }

  const record = value as Record<string, unknown>;
  const keys = ["line1", "city", "region", "postalCode", "country"] as const;
  const address: Partial<MailingAddress> = {};

  for (const key of keys) {
    const field = record[key];
    if (typeof field !== "string" || field.trim() === "") {
      return err(
        "INVALID_FIELD_VALUE",
        `company.mailingAddress.${key} must be a non-empty string.`,
      );
    }
    address[key] = field;
  }

  return ok(address as MailingAddress);
}
