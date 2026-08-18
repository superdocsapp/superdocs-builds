import { formatManagedValue } from "./profile";
import type {
  ManagedFieldPath,
  PolicyDocumentSet,
  PolicyDocumentType,
  PolicyProfile,
} from "./types";
import { ATTORNEY_REVIEW_DISCLAIMER } from "./types";

export function renderPolicySet(profile: PolicyProfile): PolicyDocumentSet {
  return {
    terms: renderTerms(profile),
    privacy: renderPrivacy(profile),
    warranty: renderWarranty(profile),
    returns: renderReturns(profile),
  };
}

export function renderTerms(profile: PolicyProfile): string {
  const name = fact(profile, "company.legalName");
  const website = fact(profile, "company.website");
  const email = fact(profile, "company.supportEmail");
  const address = fact(profile, "company.mailingAddress");
  const effective = fact(profile, "company.effectiveDate");
  const jurisdiction = fact(profile, "company.governingJurisdiction");
  const age = fact(profile, "store.minimumCustomerAge");
  const regions = fact(profile, "store.shippingRegions");
  const processor = fact(profile, "store.paymentProcessor");
  const windowDays = fact(profile, "returns.windowDays");
  const condition = fact(profile, "returns.eligibleCondition");
  const warrantyMonths = fact(profile, "warranty.durationMonths");

  const body = `
<p>${name} ("we", "us") operates ${website} and sells physical goods to customers in ${regions}.</p>
<p>These Terms of Service are effective as of ${effective}. Questions: ${email}. Mailing address: ${address}.</p>
<h2>Eligibility and orders</h2>
<p>You must be at least ${age} years old to place an order. Payments are processed by ${processor}.</p>
<h2>Returns</h2>
<p>Eligible items may be returned within ${windowDays} days of delivery if they are ${condition}. The Returns Policy states the same ${windowDays}-day window and the full process.</p>
<h2>Warranty</h2>
<p>Goods include a ${warrantyMonths}-month limited warranty against manufacturing defects. The Warranty Policy states the same ${warrantyMonths}-month duration and claim process.</p>
<h2>Governing law</h2>
<p>These terms are governed by the laws of ${jurisdiction}.</p>
`.trim();

  return wrapDocument("Terms of Service", profile, "terms", body);
}

export function renderPrivacy(profile: PolicyProfile): string {
  const name = fact(profile, "company.legalName");
  const website = fact(profile, "company.website");
  const email = fact(profile, "company.supportEmail");
  const address = fact(profile, "company.mailingAddress");
  const effective = fact(profile, "company.effectiveDate");
  const jurisdiction = fact(profile, "company.governingJurisdiction");
  const processor = fact(profile, "store.paymentProcessor");
  const categories = fact(profile, "privacy.collectedDataCategories");
  const purposes = fact(profile, "privacy.purposes");
  const processors = fact(profile, "privacy.processors");
  const analytics = fact(profile, "privacy.analyticsEnabled");
  const marketing = fact(profile, "privacy.marketingEnabled");
  const retention = fact(profile, "privacy.retentionSummary");

  const body = `
<p>This Privacy Policy describes how ${name} (${website}) handles personal information. It is effective as of ${effective} and is designed to align with expectations under ${jurisdiction}.</p>
<h2>Information we collect</h2>
<p>We collect ${categories} in order to ${purposes}.</p>
<h2>Processors and services</h2>
<p>We use ${processors}. Payments are processed by ${processor}; we do not store full payment card numbers.</p>
<h2>Analytics and marketing</h2>
<p>Analytics is ${analytics}. Marketing communications are ${marketing}.</p>
<h2>Retention</h2>
<p>We keep personal data for ${retention} unless a longer period is required to complete an order, resolve a dispute, or meet a legal obligation.</p>
<h2>Contact</h2>
<p>Privacy requests: ${email}. Mail: ${address}.</p>
`.trim();

  return wrapDocument("Privacy Policy", profile, "privacy", body);
}

export function renderWarranty(profile: PolicyProfile): string {
  const name = fact(profile, "company.legalName");
  const website = fact(profile, "company.website");
  const email = fact(profile, "company.supportEmail");
  const address = fact(profile, "company.mailingAddress");
  const effective = fact(profile, "company.effectiveDate");
  const jurisdiction = fact(profile, "company.governingJurisdiction");
  const months = fact(profile, "warranty.durationMonths");
  const covered = fact(profile, "warranty.coveredDefects");
  const exclusions = fact(profile, "warranty.exclusions");
  const claim = fact(profile, "warranty.claimMethod");

  const body = `
<p>This limited warranty is offered by ${name} (${website}) and is effective as of ${effective}.</p>
<h2>Coverage</h2>
<p>For ${months} months after delivery, we warrant against ${covered}. This ${months}-month duration matches the warranty term in our Terms of Service.</p>
<h2>What is not covered</h2>
<p>This warranty does not cover ${exclusions}.</p>
<h2>How to make a claim</h2>
<p>${claim} Contact ${email} or write to ${address}.</p>
<p>This warranty is interpreted under the laws of ${jurisdiction}.</p>
`.trim();

  return wrapDocument("Warranty Policy", profile, "warranty", body);
}

export function renderReturns(profile: PolicyProfile): string {
  const name = fact(profile, "company.legalName");
  const website = fact(profile, "company.website");
  const email = fact(profile, "company.supportEmail");
  const address = fact(profile, "company.mailingAddress");
  const effective = fact(profile, "company.effectiveDate");
  const jurisdiction = fact(profile, "company.governingJurisdiction");
  const regions = fact(profile, "store.shippingRegions");
  const windowDays = fact(profile, "returns.windowDays");
  const condition = fact(profile, "returns.eligibleCondition");
  const payer = fact(profile, "returns.returnShippingPayer");
  const refund = fact(profile, "returns.refundMethod");
  const processing = fact(profile, "returns.processingDays");
  const exceptions = fact(profile, "returns.finalSaleExceptions");

  const body = `
<p>This Returns Policy applies to physical goods sold by ${name} (${website}) into ${regions}. It is effective as of ${effective}.</p>
<h2>Return window</h2>
<p>You may return eligible items within ${windowDays} days of delivery. This ${windowDays}-day window is the same return window stated in our Terms of Service.</p>
<h2>Condition and exceptions</h2>
<p>Items must be ${condition}. Final sale and non-returnable goods include ${exceptions}.</p>
<h2>Shipping, refunds, and timing</h2>
<p>Return shipping is paid by the ${payer}. Approved refunds are issued via ${refund} within ${processing} days after we receive and inspect the return.</p>
<h2>Contact</h2>
<p>Start a return by emailing ${email} or writing to ${address}. This policy is administered under ${jurisdiction}.</p>
`.trim();

  return wrapDocument("Returns Policy", profile, "returns", body);
}

function wrapDocument(
  title: string,
  profile: PolicyProfile,
  documentType: PolicyDocumentType,
  body: string,
): string {
  return `<article class="policy-document" data-policy-document="${documentType}">
<header>
<h1>${escapeHtml(title)}</h1>
<p>${fact(profile, "company.legalName")}</p>
</header>
${body}
<footer><p>${ATTORNEY_REVIEW_DISCLAIMER}</p></footer>
</article>`;
}

function fact(profile: PolicyProfile, path: ManagedFieldPath): string {
  const value = formatManagedValue(profile, path);
  return `<span data-managed-field="${escapeHtml(path)}">${escapeHtml(value)}</span>`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
