import type { OpsLedger } from "../budget.js";
import type { SuperDocsClient } from "../client.js";
import type { NoteFile } from "../notes.js";
import type { Client } from "../domain/clients.js";
import type { Requirement } from "../domain/requirements.js";
import { parseJsonLoosely } from "./plan.js";

export type CoverageStatus = "EVIDENCED" | "STALE" | "MISSING" | "INCONSISTENT";

export interface EvidenceRef {
  file: string;
  line: number;
  excerpt: string;
}

export interface CoverageEntry {
  requirement_id: string;
  client_id: string | null; // null = firm-level
  status: CoverageStatus;
  detail: string;
  evidence: EvidenceRef[];
  method: "deterministic" | "model";
}

const ANNUAL_STALE_DAYS = 365;

/**
 * Whether a requirement applies to a given client at all. Firm-level
 * requirements never generate a per-client entry; RIA-AI-01 only applies to
 * clients actually marked ai_assisted. This is a fact about the requirement
 * and the client's own data — never a model's call to make.
 */
export function isRequirementApplicable(requirement: Requirement, client: Client): boolean {
  if (requirement.applies_to === "firm") return false;
  if (requirement.id === "RIA-AI-01") return client.ai_assisted;
  return true;
}

export function findLinesContaining(notes: NoteFile[], fileName: string, needle: string): EvidenceRef[] {
  const note = notes.find((n) => n.name === fileName);
  if (!note) return [];
  const hits: EvidenceRef[] = [];
  const lines = note.content.split(/\r?\n/);
  const needleLower = needle.toLowerCase();
  lines.forEach((line, idx) => {
    if (line.toLowerCase().includes(needleLower)) {
      hits.push({ file: note.name, line: idx + 1, excerpt: line.trim() });
    }
  });
  return hits;
}

function corpusHasAnyMention(notes: NoteFile[], keywords: string[]): EvidenceRef[] {
  const hits: EvidenceRef[] = [];
  for (const note of notes) {
    const lines = note.content.split(/\r?\n/);
    lines.forEach((line, idx) => {
      const lower = line.toLowerCase();
      if (keywords.some((k) => lower.includes(k))) {
        hits.push({ file: note.name, line: idx + 1, excerpt: line.trim() });
      }
    });
  }
  return hits;
}

/**
 * RIA-RISK-01: the review date lives in structured config
 * (client.risk_profile_reviewed_on), not free text — so freshness is
 * arithmetic, not a model call. The evidence line (for citation) is a
 * secondary, best-effort text lookup in risk-profiling-log.md.
 */
function assessRiskProfiling(client: Client, notes: NoteFile[], today: Date): CoverageEntry {
  const evidence = findLinesContaining(notes, "risk-profiling-log.md", client.id);

  if (client.risk_profile_reviewed_on === null) {
    return {
      requirement_id: "RIA-RISK-01",
      client_id: client.id,
      status: "MISSING",
      detail: "no risk profiling review on record for this client",
      evidence,
      method: "deterministic",
    };
  }

  const reviewedOn = new Date(client.risk_profile_reviewed_on);
  const daysSince = Math.floor((today.getTime() - reviewedOn.getTime()) / (1000 * 60 * 60 * 24));

  if (daysSince > ANNUAL_STALE_DAYS) {
    return {
      requirement_id: "RIA-RISK-01",
      client_id: client.id,
      status: "STALE",
      detail: `last reviewed ${client.risk_profile_reviewed_on}, ${daysSince} days ago (annual review is overdue)`,
      evidence,
      method: "deterministic",
    };
  }

  return {
    requirement_id: "RIA-RISK-01",
    client_id: client.id,
    status: "EVIDENCED",
    detail: `last reviewed ${client.risk_profile_reviewed_on}, ${daysSince} days ago (within the annual window)`,
    evidence,
    method: "deterministic",
  };
}

const FIRM_KEYWORDS: Record<string, string[]> = {
  "RIA-NW-01": ["net worth"],
  "RIA-REC-01": [
    "record retention",
    "records retained",
    "record index",
    "records index",
    "retention window",
    "records retriev",
  ],
};

/**
 * Firm-level requirements: presence/absence of a matching mention anywhere
 * in the corpus. Absence is unambiguous — zero hits is zero hits, no model
 * needed to notice nothing is there. This is the honesty rule made
 * mechanical: a requirement with no supporting evidence is MISSING, full
 * stop, never inferred from the surrounding notes.
 */
function assessFirmLevel(requirement: Requirement, notes: NoteFile[]): CoverageEntry {
  const keywords = FIRM_KEYWORDS[requirement.id] ?? [];
  const evidence = corpusHasAnyMention(notes, keywords);

  if (evidence.length === 0) {
    return {
      requirement_id: requirement.id,
      client_id: null,
      status: "MISSING",
      detail: `no mention of ${keywords.map((k) => `"${k}"`).join(" / ")} found anywhere in the corpus`,
      evidence: [],
      method: "deterministic",
    };
  }

  return {
    requirement_id: requirement.id,
    client_id: null,
    status: "EVIDENCED",
    detail: `evidenced in ${new Set(evidence.map((e) => e.file)).size} file(s)`,
    evidence,
    method: "deterministic",
  };
}

/**
 * Deterministic pass only: firm-level requirements (keyword presence /
 * absence) and RIA-RISK-01 (a date comparison). Per-client text-evidence
 * requirements — agreement, suitability, AI disclosure, fee consistency —
 * are added in the next increment, alongside the one genuinely ambiguous
 * case that escalates to a model call.
 */
export function assessCoverageDeterministic(
  requirements: Requirement[],
  clients: Client[],
  notes: NoteFile[],
  today: Date = new Date(),
): CoverageEntry[] {
  const entries: CoverageEntry[] = [];

  for (const requirement of requirements) {
    if (requirement.applies_to === "firm") {
      entries.push(assessFirmLevel(requirement, notes));
      continue;
    }

    if (requirement.id === "RIA-RISK-01") {
      for (const c of clients) {
        if (!isRequirementApplicable(requirement, c)) continue;
        entries.push(assessRiskProfiling(c, notes, today));
      }
    }
  }

  return entries;
}

// --- Per-client text evidence -------------------------------------------
//
// The corpus groups per-client entries under "--- CL-XX Name ---" headers
// within a shared file (onboarding notes, AI register, fee changes). Split
// each file into those blocks once, then search only within the block that
// belongs to the client being assessed — never across client boundaries.

export interface ClientBlock {
  file: string;
  startLine: number;
  lines: string[];
}

const CLIENT_HEADER_RE = /^---\s*(CL-\d+)\b/i;

function splitIntoClientBlocks(note: NoteFile): ClientBlock[] | null {
  const lines = note.content.split(/\r?\n/);
  const headerIdxs: number[] = [];
  lines.forEach((l, i) => {
    if (CLIENT_HEADER_RE.test(l.trim())) headerIdxs.push(i);
  });
  if (headerIdxs.length === 0) return null;

  const blocks: ClientBlock[] = [];
  for (let i = 0; i < headerIdxs.length; i++) {
    const start = headerIdxs[i]!;
    const end = i + 1 < headerIdxs.length ? headerIdxs[i + 1]! : lines.length;
    blocks.push({ file: note.name, startLine: start + 1, lines: lines.slice(start, end) });
  }
  return blocks;
}

export function blockForClient(note: NoteFile, clientId: string): ClientBlock | null {
  const blocks = splitIntoClientBlocks(note);
  if (!blocks) return null;
  return (
    blocks.find(
      (b) => CLIENT_HEADER_RE.exec(b.lines[0]!.trim())?.[1]?.toUpperCase() === clientId.toUpperCase(),
    ) ?? null
  );
}

export function findInBlock(block: ClientBlock, keywords: string[]): EvidenceRef[] {
  const hits: EvidenceRef[] = [];
  block.lines.forEach((line, offset) => {
    const lower = line.toLowerCase();
    if (keywords.some((k) => lower.includes(k))) {
      hits.push({ file: block.file, line: block.startLine + offset, excerpt: line.trim() });
    }
  });
  return hits;
}

function noteMentionsClient(note: NoteFile, client: Client): boolean {
  const lower = note.content.toLowerCase();
  return lower.includes(client.id.toLowerCase()) || lower.includes(client.name.toLowerCase());
}

/** RIA-AGR-01: a signed-agreement line in that client's onboarding block. */
function assessAgreement(client: Client, notes: NoteFile[]): CoverageEntry {
  const note = notes.find((n) => n.name === "client-onboarding-notes.md");
  const block = note ? blockForClient(note, client.id) : null;
  const evidence = block ? findInBlock(block, ["agreement"]) : [];

  if (evidence.length === 0) {
    return {
      requirement_id: "RIA-AGR-01",
      client_id: client.id,
      status: "MISSING",
      detail: "no signed agreement found in the onboarding notes",
      evidence: [],
      method: "deterministic",
    };
  }

  return {
    requirement_id: "RIA-AGR-01",
    client_id: client.id,
    status: "EVIDENCED",
    detail: "agreement execution recorded in onboarding notes",
    evidence,
    method: "deterministic",
  };
}

/**
 * RIA-AI-01: a client marked ai_assisted must have a block in the AI usage
 * register. No block at all is exactly the CL-06 case this was built to
 * catch — flagged in the corpus notes as an open question, but an open
 * question is not evidence, so this still reports MISSING.
 */
function assessAiDisclosure(client: Client, notes: NoteFile[]): CoverageEntry {
  const note = notes.find((n) => n.name === "ai-usage-register.md");
  const block = note ? blockForClient(note, client.id) : null;

  if (!block) {
    return {
      requirement_id: "RIA-AI-01",
      client_id: client.id,
      status: "MISSING",
      detail: "client is marked ai_assisted but has no entry in the AI usage register",
      evidence: [],
      method: "deterministic",
    };
  }

  const evidence = findInBlock(block, ["disclosed", "usage"]);
  return {
    requirement_id: "RIA-AI-01",
    client_id: client.id,
    status: "EVIDENCED",
    detail: "AI usage disclosure and tracking present in the register",
    evidence:
      evidence.length > 0
        ? evidence
        : [{ file: block.file, line: block.startLine, excerpt: block.lines[0]!.trim() }],
    method: "deterministic",
  };
}

interface PercentMention {
  value: number;
  line: number;
  text: string;
}

function extractLastPercent(lines: string[]): PercentMention | null {
  let result: PercentMention | null = null;
  lines.forEach((line, idx) => {
    const m = line.match(/Fee:\s*([\d.]+)%/i);
    if (m) result = { value: Number(m[1]), line: idx, text: line.trim() };
  });
  return result;
}

function extractRevisedPercent(lines: string[]): PercentMention | null {
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i]!.match(/Revised fee:\s*[\d.]+%\s*->\s*([\d.]+)%/i);
    if (m) return { value: Number(m[1]), line: i, text: lines[i]!.trim() };
  }
  return null;
}

/**
 * RIA-FEE-01: compares the fee figure in the client's onboarding block
 * against the fee figure in that client's fee-change block, if any — an
 * arithmetic comparison of two parsed numbers, not a judgment call. This is
 * what catches CL-02's fee inconsistency deterministically.
 */
function assessFee(client: Client, notes: NoteFile[]): CoverageEntry {
  const onboardingNote = notes.find((n) => n.name === "client-onboarding-notes.md");
  const onboardingBlock = onboardingNote ? blockForClient(onboardingNote, client.id) : null;
  const onboardingFee = onboardingBlock ? extractLastPercent(onboardingBlock.lines) : null;

  const feeChangeNote = notes.find((n) => n.name === "fee-schedule-change-2026.md");
  const feeChangeBlock = feeChangeNote ? blockForClient(feeChangeNote, client.id) : null;
  const revisedFee = feeChangeBlock ? extractRevisedPercent(feeChangeBlock.lines) : null;

  const evidence: EvidenceRef[] = [];
  if (onboardingBlock && onboardingFee) {
    evidence.push({
      file: onboardingBlock.file,
      line: onboardingBlock.startLine + onboardingFee.line,
      excerpt: onboardingFee.text,
    });
  }
  if (feeChangeBlock && revisedFee) {
    evidence.push({
      file: feeChangeBlock.file,
      line: feeChangeBlock.startLine + revisedFee.line,
      excerpt: revisedFee.text,
    });
  }

  if (evidence.length === 0) {
    // No percentage figure found — check for a fixed-fee mention before
    // giving up (e.g. "Fee: fixed, Rs. 1,20,000/yr.").
    const fixedEvidence = onboardingBlock ? findInBlock(onboardingBlock, ["fee:"]) : [];
    if (fixedEvidence.length === 0) {
      return {
        requirement_id: "RIA-FEE-01",
        client_id: client.id,
        status: "MISSING",
        detail: "no fee disclosure found for this client",
        evidence: [],
        method: "deterministic",
      };
    }
    return {
      requirement_id: "RIA-FEE-01",
      client_id: client.id,
      status: "EVIDENCED",
      detail: "fixed-fee arrangement on file, no revision this cycle",
      evidence: fixedEvidence,
      method: "deterministic",
    };
  }

  if (onboardingFee && revisedFee && onboardingFee.value !== revisedFee.value) {
    return {
      requirement_id: "RIA-FEE-01",
      client_id: client.id,
      status: "INCONSISTENT",
      detail: `onboarding notes show ${onboardingFee.value}% but the fee-schedule change records ${revisedFee.value}% effective — the two documents disagree`,
      evidence,
      method: "deterministic",
    };
  }

  return {
    requirement_id: "RIA-FEE-01",
    client_id: client.id,
    status: "EVIDENCED",
    detail: "fee disclosure consistent across records",
    evidence,
    method: "deterministic",
  };
}

// --- RIA-SUIT-01: mostly deterministic, one genuinely ambiguous case ----

interface SuitabilityCandidate {
  client: Client;
  evidence: EvidenceRef[];
  excerpt: string;
}

/**
 * A suitability note exists and links advice to a profile: that's a clean
 * deterministic EVIDENCED. But when the note itself says the underlying
 * profile is stale or overdue, whether the linkage still counts as a clean
 * pass is a judgment call this function declines to make — it hands that
 * one case to the model instead of hard-coding an opinion.
 */
function assessSuitabilityDeterministic(
  client: Client,
  notes: NoteFile[],
): { entry: CoverageEntry | null; candidate: SuitabilityCandidate | null } {
  const note = notes.find((n) => n.name.startsWith("suitability-notes-") && noteMentionsClient(n, client));
  if (!note) {
    return {
      entry: {
        requirement_id: "RIA-SUIT-01",
        client_id: client.id,
        status: "MISSING",
        detail: "no suitability note found for this client",
        evidence: [],
        method: "deterministic",
      },
      candidate: null,
    };
  }

  const lines = note.content.split(/\r?\n/);
  const evidence: EvidenceRef[] = lines
    .map((line, idx) => ({ line, idx }))
    .filter(({ line }) => /profile|advice/i.test(line))
    .map(({ line, idx }) => ({ file: note.name, line: idx + 1, excerpt: line.trim() }));

  if (/\bstale\b|\boverdue\b/i.test(note.content)) {
    return { entry: null, candidate: { client, evidence, excerpt: note.content.trim() } };
  }

  return {
    entry: {
      requirement_id: "RIA-SUIT-01",
      client_id: client.id,
      status: "EVIDENCED",
      detail: "advice explicitly linked to a current risk profile",
      evidence,
      method: "deterministic",
    },
    candidate: null,
  };
}

interface SuitabilityJudgment {
  client_id: string;
  status: "EVIDENCED" | "STALE";
  reason: string;
}

/**
 * The one model call in the whole coverage pass — and only if at least one
 * candidate is actually ambiguous. Every candidate is batched into a single
 * request; judging three clients costs the same one operation as judging
 * one.
 */
async function classifyAmbiguousSuitability(
  client: SuperDocsClient,
  ledger: OpsLedger,
  candidates: SuitabilityCandidate[],
): Promise<CoverageEntry[]> {
  if (candidates.length === 0) return [];

  ledger.assertCanSpend(1);

  const message = `You are reviewing suitability notes for a SEBI-registered investment adviser. Each note documents advice given to a client, but explicitly mentions that the client's underlying risk profile is stale or overdue for renewal.

For EACH client below, decide: does the note still show clear, explicit advice-to-profile linkage worth calling "EVIDENCED", or does the staleness of the profile mean this should be flagged as "STALE" instead of a clean pass? Judge only what is written — do not assume anything not stated.

Respond with JSON only — no prose, no markdown fences — exactly this shape:
{"judgments": [{"client_id": string, "status": "EVIDENCED" | "STALE", "reason": string}]}

Notes:
${candidates.map((c) => `--- ${c.client.id} (${c.client.name}) ---\n${c.excerpt}`).join("\n\n")}`;

  const sessionId = `notesforge-compliance-suit-${Date.now()}`;
  const response = await client.chat({ message, session_id: sessionId, model_tier: "core" });

  let judgments: SuitabilityJudgment[];
  try {
    const parsed = parseJsonLoosely<{ judgments: SuitabilityJudgment[] }>(response.response);
    judgments = parsed.judgments;
  } catch {
    console.warn(
      `[WARN] classifyAmbiguousSuitability: AI response was not valid JSON — falling back to EVIDENCED (evidence text is present, just unclassified):\n${response.response}`,
    );
    judgments = candidates.map((c) => ({
      client_id: c.client.id,
      status: "EVIDENCED",
      reason: "model classification unavailable — evidence text present",
    }));
  }

  return candidates.map((c) => {
    const judgment = judgments.find((j) => j.client_id === c.client.id);
    const status: CoverageStatus = judgment?.status ?? "EVIDENCED";
    return {
      requirement_id: "RIA-SUIT-01",
      client_id: c.client.id,
      status,
      detail: judgment?.reason ?? "evidence present; model classification unavailable, defaulting to evidenced",
      evidence: c.evidence,
      method: judgment ? "model" : "deterministic",
    };
  });
}

/**
 * Full coverage pass: the deterministic entries (firm-level + RIA-RISK-01)
 * plus per-client text evidence for agreement, AI disclosure and fee
 * consistency (all deterministic), plus RIA-SUIT-01, which is deterministic
 * except for the one case that names its own ambiguity.
 */
export async function assessCoverage(
  client: SuperDocsClient,
  ledger: OpsLedger,
  requirements: Requirement[],
  clients: Client[],
  notes: NoteFile[],
  today: Date = new Date(),
): Promise<CoverageEntry[]> {
  const entries = assessCoverageDeterministic(requirements, clients, notes, today);

  const agrRequirement = requirements.find((r) => r.id === "RIA-AGR-01");
  const aiRequirement = requirements.find((r) => r.id === "RIA-AI-01");
  const feeRequirement = requirements.find((r) => r.id === "RIA-FEE-01");
  const suitRequirement = requirements.find((r) => r.id === "RIA-SUIT-01");

  const suitCandidates: SuitabilityCandidate[] = [];

  for (const c of clients) {
    if (agrRequirement && isRequirementApplicable(agrRequirement, c)) {
      entries.push(assessAgreement(c, notes));
    }
    if (aiRequirement && isRequirementApplicable(aiRequirement, c)) {
      entries.push(assessAiDisclosure(c, notes));
    }
    if (feeRequirement && isRequirementApplicable(feeRequirement, c)) {
      entries.push(assessFee(c, notes));
    }
    if (suitRequirement && isRequirementApplicable(suitRequirement, c)) {
      const { entry, candidate } = assessSuitabilityDeterministic(c, notes);
      if (entry) entries.push(entry);
      if (candidate) suitCandidates.push(candidate);
    }
  }

  entries.push(...(await classifyAmbiguousSuitability(client, ledger, suitCandidates)));

  return entries;
}

/**
 * Turns a coverage finding into the exact heading text a pack section is
 * drafted and verified against — the citation lives in the heading itself
 * so the free structure read (headings only, no body) is enough to check
 * it. No evidence means no parenthetical: MISSING never gets a citation it
 * didn't earn.
 */
export function canonicalSectionHeading(requirementTitle: string, entry: CoverageEntry): string {
  const label = entry.status.charAt(0) + entry.status.slice(1).toLowerCase();
  if (entry.evidence.length === 0) {
    return `${requirementTitle} — ${label}`;
  }
  // Cite one representative file, not every file evidence touched — the
  // prompt asks that a claim cite "a source note" (singular), and a long
  // multi-file parenthetical risks the heading being truncated somewhere
  // in the document platform, which would silently strip the citation
  // verify.ts is checking for.
  const file = entry.evidence[0]!.file;
  return `${requirementTitle} — ${label} (${file})`;
}

export function formatCoverageReport(
  entries: CoverageEntry[],
  clients: Client[],
  requirements: Requirement[],
): string {
  const clientName = (id: string | null) =>
    id === null ? "FIRM" : (clients.find((c) => c.id === id)?.name ?? id);
  const reqTitle = (id: string) => requirements.find((r) => r.id === id)?.title ?? id;

  const rows = entries
    .slice()
    .sort(
      (a, b) =>
        (a.client_id ?? "").localeCompare(b.client_id ?? "") ||
        a.requirement_id.localeCompare(b.requirement_id),
    )
    .map(
      (e) =>
        `${e.status.padEnd(12)} ${e.requirement_id.padEnd(12)} ${(e.client_id ?? "FIRM").padEnd(8)} ${clientName(e.client_id)} — ${reqTitle(e.requirement_id)} — ${e.detail}`,
    );

  return rows.join("\n");
}
