import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { OpsLedger } from "../budget.js";
import type { SuperDocsClient } from "../client.js";
import type { Client } from "../domain/clients.js";
import type { Requirement } from "../domain/requirements.js";
import {
  currentVersion,
  latestClientVersion,
  recordIssue,
  registerTemplateVersion,
  type TemplateVersion,
  type VersionStore,
} from "./registry.js";

const CONFIG_TEMPLATES_DIR = fileURLToPath(new URL("../../config/templates", import.meta.url));
const STATE_TEMPLATES_DIR = fileURLToPath(new URL("../../state/templates", import.meta.url));

/**
 * Which clause in a template's text embodies a given requirement. Only
 * covers the one worked case (RIA-AI-01 → the AI-use clause in the
 * advisory agreement) — a real system would carry this mapping in the
 * template's own config, not a hardcoded table.
 */
const CLAUSE_HEADING_BY_REQUIREMENT: Record<string, string> = {
  "RIA-AI-01": "6. Use of AI Tools in Advice",
};

async function readTemplateContent(templateId: string, version: string): Promise<string> {
  const filename = `${templateId}-${version}.md`;
  try {
    return await readFile(path.join(CONFIG_TEMPLATES_DIR, filename), "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") throw err;
  }
  // Hand-authored baselines live in config/templates/; anything an
  // amendment itself produced lives in state/templates/ — generated
  // history, not hand-authored input.
  return readFile(path.join(STATE_TEMPLATES_DIR, filename), "utf8");
}

async function writeAmendedTemplateContent(templateId: string, version: string, content: string): Promise<void> {
  await mkdir(STATE_TEMPLATES_DIR, { recursive: true });
  await writeFile(path.join(STATE_TEMPLATES_DIR, `${templateId}-${version}.md`), content, "utf8");
}

export function extractClauseBody(templateContent: string, clauseHeading: string): string {
  const lines = templateContent.split(/\r?\n/);
  const headingIdx = lines.findIndex((l) => l.trim() === clauseHeading);
  if (headingIdx === -1) return "";
  const endIdx = findClauseEnd(lines, headingIdx);
  return lines
    .slice(headingIdx + 1, endIdx)
    .join(" ")
    .trim();
}

function findClauseEnd(lines: string[], headingIdx: number): number {
  for (let i = headingIdx + 1; i < lines.length; i++) {
    const trimmed = lines[i]!.trim();
    if (/^\d+\.\s/.test(trimmed) || trimmed.startsWith("Signed:")) return i;
  }
  return lines.length;
}

export function spliceClauseBody(templateContent: string, clauseHeading: string, newBody: string): string {
  const lines = templateContent.split(/\r?\n/);
  const headingIdx = lines.findIndex((l) => l.trim() === clauseHeading);
  if (headingIdx === -1) {
    throw new Error(`spliceClauseBody: heading "${clauseHeading}" not found in template`);
  }
  const endIdx = findClauseEnd(lines, headingIdx);
  return [...lines.slice(0, headingIdx + 1), `   ${newBody.trim()}`, "", ...lines.slice(endIdx)].join("\n");
}

export const DEFAULT_REQUIREMENTS_SNAPSHOT_PATH = fileURLToPath(
  new URL("../../state/requirements-snapshot.json", import.meta.url),
);

/** Missing snapshot means no amendment has ever run — not an error. */
export async function loadRequirementsSnapshot(
  filePath: string = DEFAULT_REQUIREMENTS_SNAPSHOT_PATH,
): Promise<Requirement[] | null> {
  try {
    const text = await readFile(filePath, "utf8");
    return JSON.parse(text) as Requirement[];
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw err;
  }
}

export async function saveRequirementsSnapshot(
  requirements: Requirement[],
  filePath: string = DEFAULT_REQUIREMENTS_SNAPSHOT_PATH,
): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(requirements, null, 2)}\n`, "utf8");
}

/** Hashes the substantive fields of a requirement — not its id, which is the lookup key. */
export function hashRequirementContent(r: Requirement): string {
  const material = JSON.stringify({
    citation: r.citation,
    title: r.title,
    obligation: r.obligation,
    evidence_expected: r.evidence_expected,
    frequency: r.frequency,
    applies_to: r.applies_to,
  });
  return createHash("sha256").update(material).digest("hex");
}

export type AmendmentKind = "new_requirement" | "changed_obligation";

export interface AmendmentEvent {
  requirement_id: string;
  kind: AmendmentKind;
  previous: Requirement | null;
  updated: Requirement;
}

/**
 * Compares the requirements register recorded in state against a candidate
 * updated register. Purely a content comparison — no model call, and
 * nothing here is a judgment: a requirement is either byte-for-byte the
 * same as what state last recorded, or it isn't.
 */
export function detectAmendments(baseline: Requirement[], updated: Requirement[]): AmendmentEvent[] {
  const baselineById = new Map(baseline.map((r) => [r.id, r]));
  const events: AmendmentEvent[] = [];

  for (const req of updated) {
    const prev = baselineById.get(req.id);
    if (!prev) {
      events.push({ requirement_id: req.id, kind: "new_requirement", previous: null, updated: req });
      continue;
    }
    if (hashRequirementContent(prev) !== hashRequirementContent(req)) {
      events.push({ requirement_id: req.id, kind: "changed_obligation", previous: prev, updated: req });
    }
  }

  return events;
}

export interface AmendmentScope {
  event: AmendmentEvent;
  affected_template_ids: string[];
  affected_client_ids: string[];
}

/**
 * The blast radius: which templates currently reference the changed
 * requirement, and which clients currently hold the current version of
 * one of those templates. Nothing outside this set is touched by the rest
 * of the pipeline — a client on an unrelated template, or on a superseded
 * version of an affected template, is not in scope.
 */
export function scopeAmendment(store: VersionStore, event: AmendmentEvent): AmendmentScope {
  const affectedTemplateIds = Array.from(
    new Set(
      store.template_versions
        .filter((t) => t.superseded_by === null && t.requirement_ids.includes(event.requirement_id))
        .map((t) => t.template_id),
    ),
  ).sort();

  const affectedClientIds = new Set<string>();
  for (const templateId of affectedTemplateIds) {
    const current = currentVersion(store, templateId);
    if (!current) continue;

    const holderIds = new Set(
      store.client_versions.filter((r) => r.template_id === templateId).map((r) => r.client_id),
    );
    for (const clientId of holderIds) {
      const latest = latestClientVersion(store, clientId, templateId);
      if (latest?.version === current.version) affectedClientIds.add(clientId);
    }
  }

  return {
    event,
    affected_template_ids: affectedTemplateIds,
    affected_client_ids: Array.from(affectedClientIds).sort(),
  };
}

export class AmendmentError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AmendmentError";
  }
}

/**
 * Drafts the amended clause in ONE chat call — the model sees only the
 * current clause body and the new obligation text, and returns only the
 * replacement clause body. Nothing else in the template is touched or
 * regenerated; the rest of the document is carried over verbatim from the
 * current version's content.
 */
export async function amendTemplate(
  client: SuperDocsClient,
  ledger: OpsLedger,
  store: VersionStore,
  templateId: string,
  event: AmendmentEvent,
  effectiveFrom: string,
  nextVersionLabel: string,
): Promise<TemplateVersion> {
  const current = currentVersion(store, templateId);
  if (!current) {
    throw new AmendmentError(`amendTemplate: no current version registered for "${templateId}"`);
  }

  const clauseHeading = CLAUSE_HEADING_BY_REQUIREMENT[event.requirement_id];
  if (!clauseHeading) {
    throw new AmendmentError(
      `amendTemplate: no known clause heading for requirement "${event.requirement_id}" in "${templateId}"`,
    );
  }

  const currentContent = await readTemplateContent(templateId, current.version);
  const currentClauseBody = extractClauseBody(currentContent, clauseHeading);

  // One chat call, scoped to a single clause — not a document regeneration.
  ledger.assertCanSpend(1);

  const message = `The following contractual clause needs updating because the regulatory requirement behind it has changed.

Current clause body (from the client agreement, under the heading "${clauseHeading}"):
"${currentClauseBody}"

The requirement now additionally requires:
${event.updated.obligation}

Respond with ONLY the replacement clause body text — no heading, no markdown formatting, no commentary, no code fences. One paragraph, consistent in tone and length with the original.`;

  const response = await client.chat({
    message,
    session_id: `notesforge-amend-${templateId}-${Date.now()}`,
    model_tier: "core",
  });

  const newContent = spliceClauseBody(currentContent, clauseHeading, response.response.trim());
  const requirementIds = Array.from(new Set([...current.requirement_ids, event.requirement_id]));

  const newVersion = registerTemplateVersion(
    store,
    templateId,
    nextVersionLabel,
    effectiveFrom,
    requirementIds,
    newContent,
  );

  await writeAmendedTemplateContent(templateId, newVersion.version, newContent);

  return newVersion;
}

export interface AmendmentNotice {
  client_id: string;
  client_name: string;
  template_id: string;
  requirement_id: string;
  previous_version: string;
  new_version: string;
  citation: string;
  previous_text: string;
  new_text: string;
  what_client_must_do: string;
  what_did_not_change: string[];
  consent_status: "pending";
}

/**
 * A short notice, not a reissued pack: what changed, the previous and new
 * text side by side, why (citation), what the client must do, and — just
 * as important — what explicitly did not change. An officer scanning this
 * needs the scope of a change as much as its content.
 */
export function buildAmendmentNotice(
  client: Pick<Client, "id" | "name">,
  templateId: string,
  event: AmendmentEvent,
  previousVersion: string,
  newVersion: string,
  previousClauseText: string,
  newClauseText: string,
): AmendmentNotice {
  return {
    client_id: client.id,
    client_name: client.name,
    template_id: templateId,
    requirement_id: event.requirement_id,
    previous_version: previousVersion,
    new_version: newVersion,
    citation: event.updated.citation,
    previous_text: previousClauseText,
    new_text: newClauseText,
    what_client_must_do:
      "Review the updated clause below and provide consent (see the consent block at the end of this notice). No other action is required.",
    what_did_not_change: [
      "Every other section of your agreement — scope of services, fees, conflicts of interest, term and termination, record keeping — is unchanged.",
      "Your onboarding date, fee arrangement, and every other compliance record on file for you remain exactly as they were.",
      "No client outside this notice's distribution was affected by this amendment.",
    ],
    consent_status: "pending",
  };
}

export function formatAmendmentNotice(notice: AmendmentNotice): string {
  return `AMENDMENT NOTICE — ${notice.client_name} (${notice.client_id})

Template: ${notice.template_id}   Version: ${notice.previous_version} -> ${notice.new_version}
Requirement: ${notice.requirement_id}
Why: ${notice.citation}

WHAT CHANGED

Previous clause text:
  "${notice.previous_text}"

New clause text:
  "${notice.new_text}"

WHAT YOU MUST DO

${notice.what_client_must_do}

WHAT DID NOT CHANGE

${notice.what_did_not_change.map((s) => `- ${s}`).join("\n")}

CONSENT

Status: ${notice.consent_status.toUpperCase()}
By signing below, you acknowledge and consent to the updated clause above.

Signed: ______________________   Date: ______________

---
DRAFT FOR PROFESSIONAL REVIEW — this notice is generated from source records and does not constitute compliance advice or certification.
`;
}

export interface AmendmentResult {
  event: AmendmentEvent;
  scope: AmendmentScope;
  newTemplateVersions: TemplateVersion[];
  notices: AmendmentNotice[];
}

/**
 * Ties AMEND, NOTIFY and RECORD together: for each affected template,
 * drafts the amended clause once, then for each client who actually holds
 * that template's current version — not the whole scope's client list,
 * per template — records the new issuance (consent pending, per Prompt
 * 4's writer) and builds their notice. A client outside the scope is
 * never touched: recordIssue is only ever called for a client id that
 * scopeAmendment or this function's own per-template holder check
 * produced.
 */
export async function applyAmendment(
  client: SuperDocsClient,
  ledger: OpsLedger,
  store: VersionStore,
  clients: Client[],
  event: AmendmentEvent,
  effectiveFrom: string,
  nextVersionLabel: string,
): Promise<AmendmentResult> {
  const scope = scopeAmendment(store, event);
  const newTemplateVersions: TemplateVersion[] = [];
  const notices: AmendmentNotice[] = [];

  const clauseHeading = CLAUSE_HEADING_BY_REQUIREMENT[event.requirement_id];

  for (const templateId of scope.affected_template_ids) {
    const previousVersion = currentVersion(store, templateId);
    if (!previousVersion) continue;

    const previousContent = await readTemplateContent(templateId, previousVersion.version);
    const previousClauseText = clauseHeading ? extractClauseBody(previousContent, clauseHeading) : "";

    const newVersion = await amendTemplate(client, ledger, store, templateId, event, effectiveFrom, nextVersionLabel);
    newTemplateVersions.push(newVersion);

    const newContent = await readTemplateContent(templateId, newVersion.version);
    const newClauseText = clauseHeading ? extractClauseBody(newContent, clauseHeading) : "";

    const holderIds = new Set(
      store.client_versions.filter((r) => r.template_id === templateId).map((r) => r.client_id),
    );
    const clientsOnPreviousVersion = Array.from(holderIds).filter(
      (id) => latestClientVersion(store, id, templateId)?.version === previousVersion.version,
    );

    for (const clientId of clientsOnPreviousVersion) {
      const clientRecord = clients.find((c) => c.id === clientId);
      if (!clientRecord) continue;

      recordIssue(store, clientId, templateId, newVersion.version, effectiveFrom);

      notices.push(
        buildAmendmentNotice(
          clientRecord,
          templateId,
          event,
          previousVersion.version,
          newVersion.version,
          previousClauseText,
          newClauseText,
        ),
      );
    }
  }

  return { event, scope, newTemplateVersions, notices };
}
