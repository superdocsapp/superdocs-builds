import { describe, expect, it } from "vitest";

import {
  ATTORNEY_REVIEW_DISCLAIMER,
  NORTHSTAR_GOODS_PROFILE,
  approveChangeSet,
  commitChangeSet,
  createChangeSet,
  failChangeSet,
  getAffectedDocuments,
  rejectChangeSet,
  renderPolicySet,
  renderPrivacy,
  renderReturns,
  renderTerms,
  renderWarranty,
  validatePolicySet,
  type PolicyDocumentType,
  type PolicyProfile,
  type Result,
} from "@/domain";

describe("Northstar Goods fixture", () => {
  it("starts at a 30-day return window, 12-month warranty, and 90-day retention", () => {
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.warranty.durationMonths).toBe(12);
    expect(NORTHSTAR_GOODS_PROFILE.privacy.retentionSummary).toBe("90 days");
  });
});

describe("dependency registry", () => {
  it("maps returns.windowDays exactly to terms and returns", () => {
    expect(unwrap(getAffectedDocuments("returns.windowDays"))).toEqual([
      "terms",
      "returns",
    ]);
  });

  it("maps warranty.durationMonths exactly to terms and warranty", () => {
    expect(unwrap(getAffectedDocuments("warranty.durationMonths"))).toEqual([
      "terms",
      "warranty",
    ]);
  });

  it("maps privacy.retentionSummary exactly to privacy", () => {
    expect(unwrap(getAffectedDocuments("privacy.retentionSummary"))).toEqual([
      "privacy",
    ]);
  });

  it("fails safely for an unknown managed path", () => {
    const result = getAffectedDocuments("returns.notAManagedField");
    expect(result.ok).toBe(false);
    if (result.ok) {
      return;
    }
    expect(result.error.code).toBe("UNMANAGED_FIELD_PATH");
  });

  it("does not leak a mutable registry array", () => {
    const first = unwrap(getAffectedDocuments("returns.windowDays"));
    (first as PolicyDocumentType[]).push("privacy");
    expect(unwrap(getAffectedDocuments("returns.windowDays"))).toEqual([
      "terms",
      "returns",
    ]);
  });
});

describe("ChangeSet transaction invariant", () => {
  it("can create a 30 -> 14 returns.windowDays changeset without mutating the profile", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const changeSet = unwrap(
      createChangeSet(profile, "returns.windowDays", 14),
    );

    expect(changeSet.fieldPath).toBe("returns.windowDays");
    expect(changeSet.previousValue).toBe(30);
    expect(changeSet.nextValue).toBe(14);
    expect(changeSet.affectedDocuments).toEqual(["terms", "returns"]);
    expect(changeSet.status).toBe("pending");
    expect(profile.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
  });

  it("leaves the canonical profile at 30 when the changeset is rejected", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const created = unwrap(createChangeSet(profile, "returns.windowDays", 14));
    const rejected = unwrap(rejectChangeSet(created));

    expect(rejected.status).toBe("rejected");
    expect(profile.returns.windowDays).toBe(30);
  });

  it("leaves the canonical profile at 30 when the changeset is failed", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const created = unwrap(createChangeSet(profile, "returns.windowDays", 14));
    const failed = unwrap(failChangeSet(created));

    expect(failed.status).toBe("failed");
    expect(profile.returns.windowDays).toBe(30);
  });

  it("commits an approved changeset to a new profile at 14 and leaves the original at 30", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const created = unwrap(createChangeSet(profile, "returns.windowDays", 14));
    const approved = unwrap(approveChangeSet(created));
    const committed = unwrap(commitChangeSet(profile, approved));

    expect(committed.profile).not.toBe(profile);
    expect(committed.profile.returns.windowDays).toBe(14);
    expect(profile.returns.windowDays).toBe(30);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
    expect(committed.profile.warranty.durationMonths).toBe(12);
  });

  it("refuses to commit a changeset that is not approved", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const created = unwrap(createChangeSet(profile, "returns.windowDays", 14));
    const committed = commitChangeSet(profile, created);

    expect(committed.ok).toBe(false);
    if (committed.ok) {
      return;
    }
    expect(committed.error.code).toBe("CHANGESET_NOT_APPROVED");
    expect(profile.returns.windowDays).toBe(30);
  });

  it("fails safely for an unmanaged field change", () => {
    const profile = freezeProfile(NORTHSTAR_GOODS_PROFILE);
    const created = createChangeSet(profile, "billing.taxId", "X");

    expect(created.ok).toBe(false);
    if (created.ok) {
      return;
    }
    expect(created.error.code).toBe("UNMANAGED_FIELD_PATH");
    expect(profile.returns.windowDays).toBe(30);
  });

  it("fails safely for an invalid field value", () => {
    const result = createChangeSet(
      NORTHSTAR_GOODS_PROFILE,
      "returns.windowDays",
      "14",
    );
    expect(result.ok).toBe(false);
    if (result.ok) {
      return;
    }
    expect(result.error.code).toBe("INVALID_FIELD_VALUE");
  });
});

describe("deterministic renderers", () => {
  const documents = renderPolicySet(NORTHSTAR_GOODS_PROFILE);

  it("includes the attorney-review disclaimer in all four documents", () => {
    expect(renderTerms(NORTHSTAR_GOODS_PROFILE)).toContain(
      ATTORNEY_REVIEW_DISCLAIMER,
    );
    expect(renderPrivacy(NORTHSTAR_GOODS_PROFILE)).toContain(
      ATTORNEY_REVIEW_DISCLAIMER,
    );
    expect(renderWarranty(NORTHSTAR_GOODS_PROFILE)).toContain(
      ATTORNEY_REVIEW_DISCLAIMER,
    );
    expect(renderReturns(NORTHSTAR_GOODS_PROFILE)).toContain(
      ATTORNEY_REVIEW_DISCLAIMER,
    );
  });

  it("expresses the same 30-day return window in Terms and Returns", () => {
    expect(managedValue(documents.terms, "returns.windowDays")).toBe("30");
    expect(managedValue(documents.returns, "returns.windowDays")).toBe("30");
    expect(documents.terms).toMatch(/within <span[^>]*>30<\/span> days/);
    expect(documents.returns).toMatch(/within <span[^>]*>30<\/span> days/);
  });

  it("expresses the same 12-month warranty in Terms and Warranty", () => {
    expect(managedValue(documents.terms, "warranty.durationMonths")).toBe("12");
    expect(managedValue(documents.warranty, "warranty.durationMonths")).toBe(
      "12",
    );
    expect(documents.terms).toMatch(
      /<span[^>]*>12<\/span>-month limited warranty/,
    );
    expect(documents.warranty).toMatch(/For <span[^>]*>12<\/span> months/);
  });

  it("keeps privacy retention on the privacy document only", () => {
    expect(managedValue(documents.privacy, "privacy.retentionSummary")).toBe(
      "90 days",
    );
    expect(documents.terms).not.toContain("data-managed-field=\"privacy.retentionSummary\"");
    expect(documents.returns).not.toContain("data-managed-field=\"privacy.retentionSummary\"");
    expect(documents.warranty).not.toContain("data-managed-field=\"privacy.retentionSummary\"");
  });

  it("renders a consistent Northstar policy set", () => {
    expect(validatePolicySet(NORTHSTAR_GOODS_PROFILE, documents).ok).toBe(true);
  });
});

describe("consistency validator", () => {
  it("detects a missing required document", () => {
    const documents = renderPolicySet(NORTHSTAR_GOODS_PROFILE);
    const result = validatePolicySet(NORTHSTAR_GOODS_PROFILE, {
      terms: documents.terms,
      warranty: documents.warranty,
      returns: documents.returns,
    });

    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.code === "missing_required_document")).toBe(
      true,
    );
  });

  it("detects a missing disclaimer", () => {
    const documents = renderPolicySet(NORTHSTAR_GOODS_PROFILE);
    documents.terms = documents.terms.replaceAll(ATTORNEY_REVIEW_DISCLAIMER, "");
    const result = validatePolicySet(NORTHSTAR_GOODS_PROFILE, documents);

    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.code === "missing_disclaimer")).toBe(
      true,
    );
  });

  it("detects inconsistent generated document facts", () => {
    const documents = renderPolicySet(NORTHSTAR_GOODS_PROFILE);
    documents.terms = replaceManagedField(
      documents.terms,
      "returns.windowDays",
      "14",
    );
    const result = validatePolicySet(NORTHSTAR_GOODS_PROFILE, documents);

    expect(result.ok).toBe(false);
    expect(result.issues.some((issue) => issue.code === "return_window_mismatch")).toBe(
      true,
    );
    expect(result.issues.some((issue) => issue.code === "stale_managed_fact")).toBe(
      true,
    );
  });

  it("detects a stale return window after a committed change", () => {
    const created = unwrap(
      createChangeSet(NORTHSTAR_GOODS_PROFILE, "returns.windowDays", 14),
    );
    const approved = unwrap(approveChangeSet(created));
    const committed = unwrap(
      commitChangeSet(NORTHSTAR_GOODS_PROFILE, approved),
    );
    const staleDocuments = renderPolicySet(NORTHSTAR_GOODS_PROFILE);
    const result = validatePolicySet(committed.profile, staleDocuments);

    expect(committed.profile.returns.windowDays).toBe(14);
    expect(NORTHSTAR_GOODS_PROFILE.returns.windowDays).toBe(30);
    expect(result.ok).toBe(false);
    expect(
      result.issues.some(
        (issue) =>
          issue.code === "stale_managed_fact" &&
          issue.fieldPath === "returns.windowDays",
      ),
    ).toBe(true);
  });

  it("detects company-name, support-contact, and effective-date mismatches", () => {
    const documents = renderPolicySet(NORTHSTAR_GOODS_PROFILE);
    documents.privacy = replaceManagedField(
      documents.privacy,
      "company.legalName",
      "Wrong Co",
    );
    documents.warranty = replaceManagedField(
      documents.warranty,
      "company.supportEmail",
      "other@example.test",
    );
    documents.returns = replaceManagedField(
      documents.returns,
      "company.effectiveDate",
      "1999-01-01",
    );

    const result = validatePolicySet(NORTHSTAR_GOODS_PROFILE, documents);
    const codes = result.issues.map((issue) => issue.code);

    expect(result.ok).toBe(false);
    expect(codes).toContain("company_name_mismatch");
    expect(codes).toContain("support_contact_mismatch");
    expect(codes).toContain("effective_date_mismatch");
  });

  it("accepts documents re-rendered after a committed return-window change", () => {
    const created = unwrap(
      createChangeSet(NORTHSTAR_GOODS_PROFILE, "returns.windowDays", 14),
    );
    const approved = unwrap(approveChangeSet(created));
    const committed = unwrap(
      commitChangeSet(NORTHSTAR_GOODS_PROFILE, approved),
    );
    const documents = renderPolicySet(committed.profile);

    expect(validatePolicySet(committed.profile, documents).ok).toBe(true);
    expect(managedValue(documents.terms, "returns.windowDays")).toBe("14");
    expect(managedValue(documents.returns, "returns.windowDays")).toBe("14");
  });
});

function unwrap<T>(result: Result<T>): T {
  if (!result.ok) {
    throw new Error(`${result.error.code}: ${result.error.message}`);
  }
  return result.value;
}

function freezeProfile(profile: PolicyProfile): PolicyProfile {
  return deepFreeze(structuredClone(profile));
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.freeze(value);
    for (const nested of Object.values(value)) {
      deepFreeze(nested);
    }
  }
  return value;
}

function managedValue(html: string, path: string): string | undefined {
  const match = html.match(
    new RegExp(`data-managed-field="${path}"[^>]*>([^<]*)</span>`),
  );
  return match?.[1];
}

function replaceManagedField(
  html: string,
  path: string,
  nextValue: string,
): string {
  return html.replaceAll(
    new RegExp(`(data-managed-field="${path}"[^>]*>)([^<]*)(</span>)`, "g"),
    `$1${nextValue}$3`,
  );
}
