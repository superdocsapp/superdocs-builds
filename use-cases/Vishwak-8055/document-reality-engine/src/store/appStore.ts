import { create } from "zustand";
import type { Decision, ReviewComment, ReviewEvent, ReviewEventType, ReviewTargetType, SDDocument } from "../types/domain";
import { SEED_DOCUMENTS } from "../data/documents";
import { CURRENT_USER, nextSessionTimestamp } from "../data/constants";

export interface Toast {
  id: string;
  kind: "success" | "info" | "warning";
  title: string;
  description?: string;
}

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-live-${idCounter}`;
}

function truncate(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

function updateDocument(documents: SDDocument[], documentId: string, updater: (doc: SDDocument) => SDDocument): SDDocument[] {
  return documents.map((d) => (d.id === documentId ? updater(d) : d));
}

function makeReviewEvent(
  documentId: string,
  type: ReviewEventType,
  affectedType: ReviewTargetType,
  affectedId: string,
  explanation: string,
  actor: string = CURRENT_USER,
): ReviewEvent {
  return { id: nextId("rev"), documentId, timestamp: nextSessionTimestamp(), actor, type, affectedType, affectedId, explanation };
}

interface AppState {
  documents: SDDocument[];
  commandPaletteOpen: boolean;
  toasts: Toast[];

  openCommandPalette: () => void;
  closeCommandPalette: () => void;
  toggleCommandPalette: () => void;
  pushToast: (toast: Omit<Toast, "id">) => void;
  dismissToast: (id: string) => void;

  verifyClaim: (documentId: string, claimId: string) => void;
  markEvidenceStale: (documentId: string, evidenceId: string) => void;
  resolveRisk: (documentId: string, riskId: string) => void;
  addComment: (documentId: string, targetType: ReviewComment["targetType"], targetId: string, text: string) => void;
  assignAction: (documentId: string, actionId: string, assignee: string) => void;
  completeAction: (documentId: string, actionId: string) => void;
  approveDocument: (documentId: string, note?: string) => void;
  requestChanges: (documentId: string, note: string) => void;
}

export const useAppStore = create<AppState>()((set, get) => ({
  documents: SEED_DOCUMENTS,
  commandPaletteOpen: false,
  toasts: [],

  openCommandPalette: () => set({ commandPaletteOpen: true }),
  closeCommandPalette: () => set({ commandPaletteOpen: false }),
  toggleCommandPalette: () => set((s) => ({ commandPaletteOpen: !s.commandPaletteOpen })),

  pushToast: (toast) => set((s) => ({ toasts: [...s.toasts, { ...toast, id: nextId("toast") }] })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  verifyClaim: (documentId, claimId) => {
    let claimText = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const target = doc.claims.find((c) => c.id === claimId);
        if (!target) return doc;
        claimText = target.text;
        const claims = doc.claims.map((c) =>
          c.id === claimId
            ? {
                ...c,
                verificationStatus: "Verified" as const,
                confidence: Math.max(c.confidence, 90),
                lastVerifiedAt: nextSessionTimestamp(),
                reviewer: CURRENT_USER,
                contradictionNote: undefined,
              }
            : c,
        );
        const event = makeReviewEvent(doc.id, "Claim Verified", "Claim", claimId, `Marked "${truncate(target.text)}" as verified.`);
        return { ...doc, claims, reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (claimText) get().pushToast({ kind: "success", title: "Claim verified", description: truncate(claimText, 72) });
  },

  markEvidenceStale: (documentId, evidenceId) => {
    let evidenceTitle = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const target = doc.evidence.find((e) => e.id === evidenceId);
        if (!target) return doc;
        evidenceTitle = target.title;
        const evidence = doc.evidence.map((e) => (e.id === evidenceId ? { ...e, reviewerOverride: "Stale" as const } : e));
        const event = makeReviewEvent(doc.id, "Evidence Marked Stale", "Evidence", evidenceId, `Flagged "${target.title}" as stale for renewal.`);
        return { ...doc, evidence, reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (evidenceTitle) get().pushToast({ kind: "info", title: "Evidence flagged as stale", description: evidenceTitle });
  },

  resolveRisk: (documentId, riskId) => {
    let riskTitle = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const target = doc.risks.find((r) => r.id === riskId);
        if (!target) return doc;
        riskTitle = target.title;
        const risks = doc.risks.map((r) => (r.id === riskId ? { ...r, status: "Mitigated" as const } : r));
        const event = makeReviewEvent(doc.id, "Finding Resolved", "Risk", riskId, `Resolved: ${target.title}`);
        return { ...doc, risks, reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (riskTitle) get().pushToast({ kind: "success", title: "Finding resolved", description: riskTitle });
  },

  addComment: (documentId, targetType, targetId, text) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const comment: ReviewComment = {
          id: nextId("comment"),
          documentId,
          targetType,
          targetId,
          author: CURRENT_USER,
          text: trimmed,
          createdAt: nextSessionTimestamp(),
        };
        const event = makeReviewEvent(doc.id, "Comment Added", targetType, targetId, `Commented: "${truncate(trimmed)}"`);
        return { ...doc, comments: [...doc.comments, comment], reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    get().pushToast({ kind: "info", title: "Comment added" });
  },

  assignAction: (documentId, actionId, assignee) => {
    const trimmed = assignee.trim();
    if (!trimmed) return;
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const actions = doc.actions.map((a) => (a.id === actionId ? { ...a, assignee: trimmed } : a));
        const event = makeReviewEvent(doc.id, "Action Assigned", "Action", actionId, `Assigned to ${trimmed}.`);
        return { ...doc, actions, reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    get().pushToast({ kind: "info", title: "Action assigned", description: trimmed });
  },

  completeAction: (documentId, actionId) => {
    let actionTitle = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        const target = doc.actions.find((a) => a.id === actionId);
        if (!target) return doc;
        actionTitle = target.title;
        const actions = doc.actions.map((a) => (a.id === actionId ? { ...a, status: "Done" as const } : a));
        const event = makeReviewEvent(doc.id, "Action Completed", "Action", actionId, `Completed: ${target.title}`);
        return { ...doc, actions, reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (actionTitle) get().pushToast({ kind: "success", title: "Action completed", description: actionTitle });
  },

  approveDocument: (documentId, note) => {
    let title = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        title = doc.title;
        const decision: Decision = {
          id: nextId("dec"),
          documentId,
          description: `Approve ${doc.title}`,
          outcome: "Approved",
          decidedBy: CURRENT_USER,
          decidedAt: nextSessionTimestamp(),
          notes: note?.trim() || undefined,
        };
        const event = makeReviewEvent(doc.id, "Approval Granted", "Document", doc.id, note?.trim() || "Approved with no additional notes.");
        return { ...doc, status: "Approved", decisions: [...doc.decisions, decision], reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (title) get().pushToast({ kind: "success", title: "Document approved", description: title });
  },

  requestChanges: (documentId, note) => {
    const trimmed = note.trim();
    if (!trimmed) return;
    let title = "";
    set((s) => ({
      documents: updateDocument(s.documents, documentId, (doc) => {
        title = doc.title;
        const decision: Decision = {
          id: nextId("dec"),
          documentId,
          description: `Request changes on ${doc.title}`,
          outcome: "Deferred",
          decidedBy: CURRENT_USER,
          decidedAt: nextSessionTimestamp(),
          notes: trimmed,
        };
        const event = makeReviewEvent(doc.id, "Changes Requested", "Document", doc.id, trimmed);
        return { ...doc, decisions: [...doc.decisions, decision], reviewEvents: [...doc.reviewEvents, event] };
      }),
    }));
    if (title) get().pushToast({ kind: "warning", title: "Changes requested", description: title });
  },
}));

export function useDocument(id: string | undefined): SDDocument | undefined {
  return useAppStore((s) => s.documents.find((d) => d.id === id));
}
