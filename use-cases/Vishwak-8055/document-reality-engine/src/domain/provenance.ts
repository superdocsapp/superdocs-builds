import type { Claim, Evidence, ProvenanceRecord, ReviewEvent, SDDocument } from "../types/domain";

export interface ProvenanceNode {
  kind: "claim" | "evidence" | "source" | "verification";
  title: string;
  detail: string;
  /** Whether this link in the chain is actually present, or a gap in the record. */
  present: boolean;
  timestamp?: string;
}

export interface ProvenanceTrace {
  claim: Claim;
  evidence: Evidence[];
  verificationEvents: ReviewEvent[];
  records: ProvenanceRecord[];
  /** A flattened, render-ready chain: Claim → Evidence → Source → Verification. */
  nodes: ProvenanceNode[];
}

/**
 * Traces a single claim back through its evidence, the named source of that
 * evidence, and the review event (if any) that verified or contradicted it.
 * Missing links are returned as `present: false` nodes rather than omitted,
 * so a broken chain is visible instead of silently absent.
 */
export function traceClaim(document: SDDocument, claimId: string): ProvenanceTrace | null {
  const claim = document.claims.find((c) => c.id === claimId);
  if (!claim) return null;

  const evidence = document.evidence.filter((e) => claim.evidenceIds.includes(e.id));
  const verificationEvents = document.reviewEvents.filter(
    (ev) => ev.affectedId === claimId && (ev.type === "Claim Verified" || ev.type === "Claim Contradicted"),
  );
  const records = document.provenance.filter(
    (p) => (p.subjectType === "Claim" && p.subjectId === claimId) || (p.subjectType === "Evidence" && evidence.some((e) => e.id === p.subjectId)),
  );

  const nodes: ProvenanceNode[] = [
    { kind: "claim", title: "Claim", detail: claim.text, present: true },
  ];

  if (evidence.length > 0) {
    for (const e of evidence) {
      nodes.push({ kind: "evidence", title: e.title, detail: e.description, present: true, timestamp: e.collectedAt });
    }
  } else {
    nodes.push({ kind: "evidence", title: "No evidence attached", detail: "This claim has not been linked to any supporting evidence.", present: false });
  }

  if (evidence.length > 0) {
    for (const e of evidence) {
      nodes.push({ kind: "source", title: e.sourceName, detail: `${e.sourceType}${e.reference ? ` · ${e.reference}` : ""}`, present: true });
    }
  } else {
    nodes.push({ kind: "source", title: "No named source", detail: "Cannot attribute this claim to a source without evidence.", present: false });
  }

  if (verificationEvents.length > 0) {
    for (const ev of verificationEvents) {
      nodes.push({ kind: "verification", title: ev.type, detail: `${ev.actor} — ${ev.explanation}`, present: true, timestamp: ev.timestamp });
    }
  } else {
    nodes.push({
      kind: "verification",
      title: "Not yet verified",
      detail: "No reviewer has verified or contradicted this claim.",
      present: false,
    });
  }

  return { claim, evidence, verificationEvents, records, nodes };
}
