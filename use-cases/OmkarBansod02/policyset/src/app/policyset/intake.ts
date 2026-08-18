import {
  applyManagedField,
  clonePolicyProfile,
  getManagedFieldValue,
  MANAGED_FIELD_PATHS,
  parseManagedFieldValue,
  type PolicyProfile,
  type Result,
  type ReturnShippingPayer,
} from "@/domain";

export type IntakeFormState = {
  company: {
    legalName: string;
    website: string;
    supportEmail: string;
    mailingAddress: {
      line1: string;
      city: string;
      region: string;
      postalCode: string;
      country: string;
    };
    effectiveDate: string;
    governingJurisdiction: string;
  };
  store: {
    minimumCustomerAge: number;
    shippingRegions: string;
    paymentProcessor: string;
  };
  returns: {
    windowDays: number;
    eligibleCondition: string;
    returnShippingPayer: ReturnShippingPayer;
    refundMethod: string;
    processingDays: number;
    finalSaleExceptions: string;
  };
  warranty: {
    durationMonths: number;
    coveredDefects: string;
    exclusions: string;
    claimMethod: string;
  };
  privacy: {
    collectedDataCategories: string;
    purposes: string;
    processors: string;
    analyticsEnabled: boolean;
    marketingEnabled: boolean;
    retentionSummary: string;
  };
};

export function intakeFromProfile(profile: PolicyProfile): IntakeFormState {
  return {
    company: {
      legalName: profile.company.legalName,
      website: profile.company.website,
      supportEmail: profile.company.supportEmail,
      mailingAddress: { ...profile.company.mailingAddress },
      effectiveDate: profile.company.effectiveDate,
      governingJurisdiction: profile.company.governingJurisdiction,
    },
    store: {
      minimumCustomerAge: profile.store.minimumCustomerAge,
      shippingRegions: joinList(profile.store.shippingRegions),
      paymentProcessor: profile.store.paymentProcessor,
    },
    returns: {
      windowDays: profile.returns.windowDays,
      eligibleCondition: profile.returns.eligibleCondition,
      returnShippingPayer: profile.returns.returnShippingPayer,
      refundMethod: profile.returns.refundMethod,
      processingDays: profile.returns.processingDays,
      finalSaleExceptions: joinList(profile.returns.finalSaleExceptions),
    },
    warranty: { ...profile.warranty },
    privacy: {
      collectedDataCategories: joinList(profile.privacy.collectedDataCategories),
      purposes: joinList(profile.privacy.purposes),
      processors: joinList(profile.privacy.processors),
      analyticsEnabled: profile.privacy.analyticsEnabled,
      marketingEnabled: profile.privacy.marketingEnabled,
      retentionSummary: profile.privacy.retentionSummary,
    },
  };
}

export function profileFromIntake(
  intake: IntakeFormState,
): Result<PolicyProfile> {
  const candidate: PolicyProfile = {
    company: {
      legalName: intake.company.legalName.trim(),
      website: intake.company.website.trim(),
      supportEmail: intake.company.supportEmail.trim(),
      mailingAddress: {
        line1: intake.company.mailingAddress.line1.trim(),
        city: intake.company.mailingAddress.city.trim(),
        region: intake.company.mailingAddress.region.trim(),
        postalCode: intake.company.mailingAddress.postalCode.trim(),
        country: intake.company.mailingAddress.country.trim(),
      },
      effectiveDate: intake.company.effectiveDate.trim(),
      governingJurisdiction: intake.company.governingJurisdiction.trim(),
    },
    store: {
      minimumCustomerAge: intake.store.minimumCustomerAge,
      shippingRegions: splitList(intake.store.shippingRegions),
      paymentProcessor: intake.store.paymentProcessor.trim(),
    },
    returns: {
      windowDays: intake.returns.windowDays,
      eligibleCondition: intake.returns.eligibleCondition.trim(),
      returnShippingPayer: intake.returns.returnShippingPayer,
      refundMethod: intake.returns.refundMethod.trim(),
      processingDays: intake.returns.processingDays,
      finalSaleExceptions: splitList(intake.returns.finalSaleExceptions),
    },
    warranty: {
      durationMonths: intake.warranty.durationMonths,
      coveredDefects: intake.warranty.coveredDefects.trim(),
      exclusions: intake.warranty.exclusions.trim(),
      claimMethod: intake.warranty.claimMethod.trim(),
    },
    privacy: {
      collectedDataCategories: splitList(intake.privacy.collectedDataCategories),
      purposes: splitList(intake.privacy.purposes),
      processors: splitList(intake.privacy.processors),
      analyticsEnabled: intake.privacy.analyticsEnabled,
      marketingEnabled: intake.privacy.marketingEnabled,
      retentionSummary: intake.privacy.retentionSummary.trim(),
    },
  };

  return parseIntakeProfile(candidate);
}

export function parseIntakeProfile(
  profile: PolicyProfile,
): Result<PolicyProfile> {
  let next = clonePolicyProfile(profile);

  for (const path of MANAGED_FIELD_PATHS) {
    const parsed = parseManagedFieldValue(
      path,
      getManagedFieldValue(next, path),
    );
    if (!parsed.ok) {
      return parsed;
    }
    next = applyManagedField(next, path, parsed.value);
  }

  return { ok: true, value: next };
}

export function joinList(values: readonly string[]): string {
  return values.join(", ");
}

export function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}
