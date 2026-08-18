import type { PolicyProfile } from "../types";

export const NORTHSTAR_GOODS_PROFILE: PolicyProfile = {
  company: {
    legalName: "Northstar Goods LLC",
    website: "https://www.northstar.goods.test",
    supportEmail: "support@northstar.goods.test",
    mailingAddress: {
      line1: "100 Example Wharf, Suite 4",
      city: "Harbor City",
      region: "OR",
      postalCode: "99999",
      country: "United States",
    },
    effectiveDate: "2026-01-15",
    governingJurisdiction: "State of Oregon, United States",
  },
  store: {
    minimumCustomerAge: 18,
    shippingRegions: ["United States", "Canada"],
    paymentProcessor: "Stripe",
  },
  returns: {
    windowDays: 30,
    eligibleCondition:
      "unused, in original packaging, and accompanied by proof of purchase",
    returnShippingPayer: "customer",
    refundMethod: "original payment method",
    processingDays: 7,
    finalSaleExceptions: [
      "gift cards",
      "personalized goods",
      "clearance items marked final sale",
    ],
  },
  warranty: {
    durationMonths: 12,
    coveredDefects: "manufacturing defects in materials and workmanship",
    exclusions:
      "normal wear, misuse, unauthorized repair, and consumable parts",
    claimMethod:
      "Email support with your order number and photos of the defect.",
  },
  privacy: {
    collectedDataCategories: [
      "contact details",
      "order history",
      "payment confirmation",
      "device data",
    ],
    purposes: [
      "fulfill orders",
      "provide customer support",
      "meet legal obligations",
      "operate optional analytics",
    ],
    processors: ["Stripe", "parcel carriers"],
    analyticsEnabled: true,
    marketingEnabled: false,
    retentionSummary: "90 days",
  },
};
