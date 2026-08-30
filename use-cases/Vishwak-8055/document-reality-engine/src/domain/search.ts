import type { SDDocument } from "../types/domain";
import { unsupportedClaims } from "./claims";
import { isEvidenceStale } from "./evidence";
import { unresolvedRequirements } from "./compliance";
import { computeRisk } from "./risk";

export type SearchResultKind = "Document" | "Claim" | "Evidence" | "Requirement" | "Risk" | "Reviewer";

export interface SearchResult {
  id: string;
  kind: SearchResultKind;
  title: string;
  subtitle: string;
  documentId: string;
  documentTitle: string;
  navigateTo: string;
}

export interface CommandDefinition {
  id: string;
  label: string;
  keywords: string[];
  description: string;
  run: (documents: SDDocument[]) => SearchResult[];
}

export const COMMANDS: CommandDefinition[] = [
  {
    id: "unsupported-claims",
    label: "Find unsupported claims",
    keywords: ["unsupported", "claims", "no evidence", "unproven"],
    description: "Claims with no linked evidence, or marked unverified / contradicted",
    run: (documents) =>
      documents.flatMap((doc) =>
        unsupportedClaims(doc.claims).map((claim) => ({
          id: claim.id,
          kind: "Claim" as const,
          title: claim.text,
          subtitle: `${claim.verificationStatus} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/claims?claim=${claim.id}`,
        })),
      ),
  },
  {
    id: "high-risk-documents",
    label: "Show high-risk documents",
    keywords: ["high risk", "high-risk", "critical", "risky"],
    description: "Documents currently assessed High or Critical risk",
    run: (documents) =>
      documents
        .map((doc) => ({ doc, assessment: computeRisk(doc) }))
        .filter(({ assessment }) => assessment.level === "High" || assessment.level === "Critical")
        .sort((a, b) => b.assessment.score - a.assessment.score)
        .map(({ doc, assessment }) => ({
          id: doc.id,
          kind: "Document" as const,
          title: doc.title,
          subtitle: `${assessment.level} risk · ${assessment.openCount} open findings`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/risk`,
        })),
  },
  {
    id: "unresolved-requirements",
    label: "Show unresolved requirements",
    keywords: ["unresolved", "requirements", "failed", "warnings", "compliance"],
    description: "Requirements with a Warning or Failed status",
    run: (documents) =>
      documents.flatMap((doc) =>
        unresolvedRequirements(doc.requirements).map((req) => ({
          id: req.id,
          kind: "Requirement" as const,
          title: req.description,
          subtitle: `${req.status} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/requirements?requirement=${req.id}`,
        })),
      ),
  },
  {
    id: "recently-changed-claims",
    label: "Find recently changed claims",
    keywords: ["recent", "recently changed", "changed claims", "redline"],
    description: "Claims touched by the most recent change on their document",
    run: (documents) =>
      documents.flatMap((doc) => {
        if (doc.changes.length === 0) return [];
        const mostRecent = [...doc.changes].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime())[0]!;
        return mostRecent.claimChangeIds
          .map((claimId) => doc.claims.find((c) => c.id === claimId))
          .filter((c): c is NonNullable<typeof c> => Boolean(c))
          .map((claim) => ({
            id: claim.id,
            kind: "Claim" as const,
            title: claim.text,
            subtitle: `Changed in v${mostRecent.toVersion} · ${doc.title}`,
            documentId: doc.id,
            documentTitle: doc.title,
            navigateTo: `/documents/${doc.id}/claims?claim=${claim.id}`,
          }));
      }),
  },
  {
    id: "stale-evidence",
    label: "Show stale evidence",
    keywords: ["stale", "expired", "outdated evidence"],
    description: "Evidence past its validity window or overdue for renewal",
    run: (documents) =>
      documents.flatMap((doc) =>
        doc.evidence
          .filter((e) => isEvidenceStale(e))
          .map((e) => ({
            id: e.id,
            kind: "Evidence" as const,
            title: e.title,
            subtitle: `${e.sourceType} · ${doc.title}`,
            documentId: doc.id,
            documentTitle: doc.title,
            navigateTo: `/documents/${doc.id}/claims?evidence=${e.id}`,
          })),
      ),
  },
  {
    id: "awaiting-approval",
    label: "Show documents awaiting approval",
    keywords: ["awaiting approval", "pending approval", "in review"],
    description: "Documents currently In Review",
    run: (documents) =>
      documents
        .filter((doc) => doc.status === "In Review")
        .map((doc) => ({
          id: doc.id,
          kind: "Document" as const,
          title: doc.title,
          subtitle: `In Review · owned by ${doc.owner.name}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/reviews`,
        })),
  },
];

function scoreCommandMatch(command: CommandDefinition, query: string): number {
  const q = query.toLowerCase().trim();
  if (!q) return 0;
  if (command.label.toLowerCase() === q) return 100;
  if (command.label.toLowerCase().includes(q)) return 80;
  if (command.keywords.some((k) => k === q)) return 70;
  if (command.keywords.some((k) => k.includes(q) || q.includes(k))) return 50;
  return 0;
}

function textSearch(documents: SDDocument[], query: string): SearchResult[] {
  const q = query.toLowerCase().trim();
  if (!q) return [];
  const results: SearchResult[] = [];

  for (const doc of documents) {
    if (doc.title.toLowerCase().includes(q) || (doc.counterparty ?? "").toLowerCase().includes(q)) {
      results.push({
        id: doc.id,
        kind: "Document",
        title: doc.title,
        subtitle: `${doc.type} · ${doc.status}`,
        documentId: doc.id,
        documentTitle: doc.title,
        navigateTo: `/documents/${doc.id}`,
      });
    }
    if (doc.owner.name.toLowerCase().includes(q)) {
      results.push({
        id: `${doc.id}-owner`,
        kind: "Reviewer",
        title: doc.owner.name,
        subtitle: `Owner · ${doc.title}`,
        documentId: doc.id,
        documentTitle: doc.title,
        navigateTo: `/documents/${doc.id}/reviews`,
      });
    }
    for (const claim of doc.claims) {
      if (claim.text.toLowerCase().includes(q) || claim.claimant.toLowerCase().includes(q)) {
        results.push({
          id: claim.id,
          kind: "Claim",
          title: claim.text,
          subtitle: `${claim.verificationStatus} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/claims?claim=${claim.id}`,
        });
      }
      if (claim.reviewer && claim.reviewer.toLowerCase().includes(q)) {
        results.push({
          id: `${claim.id}-reviewer`,
          kind: "Reviewer",
          title: claim.reviewer,
          subtitle: `Reviewed a claim · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/claims?claim=${claim.id}`,
        });
      }
    }
    for (const e of doc.evidence) {
      if (e.title.toLowerCase().includes(q) || e.sourceName.toLowerCase().includes(q)) {
        results.push({
          id: e.id,
          kind: "Evidence",
          title: e.title,
          subtitle: `${e.sourceName} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/claims?evidence=${e.id}`,
        });
      }
    }
    for (const r of doc.requirements) {
      if (r.description.toLowerCase().includes(q)) {
        results.push({
          id: r.id,
          kind: "Requirement",
          title: r.description,
          subtitle: `${r.status} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/requirements?requirement=${r.id}`,
        });
      }
    }
    for (const r of doc.risks) {
      if (r.title.toLowerCase().includes(q)) {
        results.push({
          id: r.id,
          kind: "Risk",
          title: r.title,
          subtitle: `${r.severity} · ${doc.title}`,
          documentId: doc.id,
          documentTitle: doc.title,
          navigateTo: `/documents/${doc.id}/risk?risk=${r.id}`,
        });
      }
    }
  }

  return results;
}

export interface SearchOutcome {
  matchedCommand: CommandDefinition | null;
  results: SearchResult[];
}

const MAX_RESULTS = 24;

export function runSearch(documents: SDDocument[], query: string): SearchOutcome {
  const trimmed = query.trim();
  if (!trimmed) return { matchedCommand: null, results: [] };

  const ranked = COMMANDS.map((command) => ({ command, score: scoreCommandMatch(command, trimmed) }))
    .filter((c) => c.score > 0)
    .sort((a, b) => b.score - a.score);

  if (ranked.length > 0 && ranked[0]!.score >= 50) {
    const command = ranked[0]!.command;
    return { matchedCommand: command, results: command.run(documents).slice(0, MAX_RESULTS) };
  }

  return { matchedCommand: null, results: textSearch(documents, trimmed).slice(0, MAX_RESULTS) };
}
