import { beforeEach, describe, expect, it } from "vitest";
import { useAppStore } from "../../store/appStore";
import { SEED_DOCUMENTS } from "../../data/documents";
import { computeRisk } from "../../domain/risk";

const IRONCLAD = "doc-ironclad-msa";

function getIronclad() {
  const doc = useAppStore.getState().documents.find((d) => d.id === IRONCLAD);
  if (!doc) throw new Error("fixture document missing from store");
  return doc;
}

beforeEach(() => {
  useAppStore.setState({ documents: SEED_DOCUMENTS, toasts: [], commandPaletteOpen: false });
});

describe("useAppStore", () => {
  it("verifyClaim marks a claim Verified, records a reviewer, and appends an audit event — without touching the seed data", () => {
    useAppStore.getState().verifyClaim(IRONCLAD, "claim-ic-01");

    const claim = getIronclad().claims.find((c) => c.id === "claim-ic-01")!;
    expect(claim.verificationStatus).toBe("Verified");
    expect(claim.reviewer).toBe("You");
    expect(claim.contradictionNote).toBeUndefined();

    const lastEvent = getIronclad().reviewEvents.at(-1)!;
    expect(lastEvent.type).toBe("Claim Verified");
    expect(lastEvent.affectedId).toBe("claim-ic-01");

    const originalClaim = SEED_DOCUMENTS.find((d) => d.id === IRONCLAD)!.claims.find((c) => c.id === "claim-ic-01")!;
    expect(originalClaim.verificationStatus).toBe("Contradicted");

    expect(useAppStore.getState().toasts.some((t) => t.title === "Claim verified")).toBe(true);
  });

  it("resolveRisk moves a risk to Mitigated and lowers the computed risk score", () => {
    const before = computeRisk(getIronclad());
    useAppStore.getState().resolveRisk(IRONCLAD, "risk-ic-03"); // Medium, weight 2

    const risk = getIronclad().risks.find((r) => r.id === "risk-ic-03")!;
    expect(risk.status).toBe("Mitigated");

    const after = computeRisk(getIronclad());
    expect(after.score).toBe(before.score - 2);
    expect(after.openCount).toBe(before.openCount - 1);
  });

  it("markEvidenceStale sets a reviewer override that isEvidenceStale respects", () => {
    useAppStore.getState().markEvidenceStale(IRONCLAD, "ev-ic-03");
    const evidence = getIronclad().evidence.find((e) => e.id === "ev-ic-03")!;
    expect(evidence.reviewerOverride).toBe("Stale");
  });

  it("addComment appends a comment and an audit event, and ignores blank text", () => {
    useAppStore.getState().addComment(IRONCLAD, "Claim", "claim-ic-03", "Let's chase the vendor for a firm date.");
    expect(getIronclad().comments.some((c) => c.text === "Let's chase the vendor for a firm date.")).toBe(true);
    expect(getIronclad().reviewEvents.at(-1)?.type).toBe("Comment Added");

    const eventCountBefore = getIronclad().reviewEvents.length;
    useAppStore.getState().addComment(IRONCLAD, "Claim", "claim-ic-03", "   ");
    expect(getIronclad().reviewEvents.length).toBe(eventCountBefore);
  });

  it("completeAction marks an action Done and logs it", () => {
    useAppStore.getState().completeAction(IRONCLAD, "act-ic-01");
    expect(getIronclad().actions.find((a) => a.id === "act-ic-01")?.status).toBe("Done");
    expect(getIronclad().reviewEvents.at(-1)?.type).toBe("Action Completed");
  });

  it("assignAction reassigns an action and ignores a blank assignee", () => {
    useAppStore.getState().assignAction(IRONCLAD, "act-ic-04", "Gabrielle Okafor");
    expect(getIronclad().actions.find((a) => a.id === "act-ic-04")?.assignee).toBe("Gabrielle Okafor");

    useAppStore.getState().assignAction(IRONCLAD, "act-ic-04", "   ");
    expect(getIronclad().actions.find((a) => a.id === "act-ic-04")?.assignee).toBe("Gabrielle Okafor");
  });

  it("approveDocument transitions status to Approved and records a Decision", () => {
    useAppStore.getState().approveDocument(IRONCLAD, "Approved with conditions.");
    const doc = getIronclad();
    expect(doc.status).toBe("Approved");
    expect(doc.decisions.at(-1)).toMatchObject({ outcome: "Approved", decidedBy: "You", notes: "Approved with conditions." });
  });

  it("requestChanges records a Deferred decision without changing document status, and requires a note", () => {
    useAppStore.getState().requestChanges(IRONCLAD, "Need the updated SOC 2 report first.");
    const doc = getIronclad();
    expect(doc.status).toBe("In Review");
    expect(doc.decisions.at(-1)).toMatchObject({ outcome: "Deferred" });

    const decisionCountBefore = doc.decisions.length;
    useAppStore.getState().requestChanges(IRONCLAD, "");
    expect(getIronclad().decisions.length).toBe(decisionCountBefore);
  });

  it("manages the toast queue", () => {
    useAppStore.getState().pushToast({ kind: "info", title: "Hello" });
    const toast = useAppStore.getState().toasts.at(-1)!;
    expect(toast.title).toBe("Hello");
    useAppStore.getState().dismissToast(toast.id);
    expect(useAppStore.getState().toasts.find((t) => t.id === toast.id)).toBeUndefined();
  });

  it("toggles the command palette", () => {
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
    useAppStore.getState().toggleCommandPalette();
    expect(useAppStore.getState().commandPaletteOpen).toBe(true);
    useAppStore.getState().closeCommandPalette();
    expect(useAppStore.getState().commandPaletteOpen).toBe(false);
  });
});
