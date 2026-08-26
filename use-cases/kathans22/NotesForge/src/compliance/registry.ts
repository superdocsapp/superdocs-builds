import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

export interface TemplateVersion {
  template_id: string;
  version: string;
  effective_from: string;
  requirement_ids: string[];
  content_hash: string;
  superseded_by: string | null;
}

export interface ClientVersionRecord {
  client_id: string;
  template_id: string;
  version: string;
  issued_on: string;
  consented_on: string | null;
  consent_evidence: string | null;
}

export interface VersionStore {
  template_versions: TemplateVersion[];
  client_versions: ClientVersionRecord[];
}

export const DEFAULT_VERSION_STORE_PATH = fileURLToPath(new URL("../../state/versions.json", import.meta.url));

export class RegistryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "RegistryError";
  }
}

function emptyStore(): VersionStore {
  return { template_versions: [], client_versions: [] };
}

/** Missing store file is a fresh register, not an error — this is the first run. */
export async function loadVersionStore(filePath: string = DEFAULT_VERSION_STORE_PATH): Promise<VersionStore> {
  try {
    const text = await readFile(filePath, "utf8");
    return JSON.parse(text) as VersionStore;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return emptyStore();
    }
    throw err;
  }
}

export async function saveVersionStore(
  store: VersionStore,
  filePath: string = DEFAULT_VERSION_STORE_PATH,
): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(store, null, 2)}\n`, "utf8");
}

export function hashTemplateContent(content: string): string {
  return createHash("sha256").update(content.trim()).digest("hex");
}

/** The template_versions entry for this template with nothing superseding it. */
export function currentVersion(store: VersionStore, templateId: string): TemplateVersion | null {
  return store.template_versions.find((t) => t.template_id === templateId && t.superseded_by === null) ?? null;
}

/**
 * Registers a template version, identified by its content hash rather than
 * the version label someone typed. If this exact content has already been
 * registered for this template — under any label — that existing entry is
 * returned unchanged; two versions with identical content are one and the
 * same, not a duplicate. Otherwise this is a genuinely new version, and it
 * supersedes whatever was previously current: only the forward-pointing
 * `superseded_by` link on the old entry changes, never its content, hash or
 * effective date.
 */
export function registerTemplateVersion(
  store: VersionStore,
  templateId: string,
  version: string,
  effectiveFrom: string,
  requirementIds: string[],
  content: string,
): TemplateVersion {
  const contentHash = hashTemplateContent(content);

  const existing = store.template_versions.find(
    (t) => t.template_id === templateId && t.content_hash === contentHash,
  );
  if (existing) return existing;

  const previousCurrent = currentVersion(store, templateId);

  const entry: TemplateVersion = {
    template_id: templateId,
    version,
    effective_from: effectiveFrom,
    requirement_ids: requirementIds,
    content_hash: contentHash,
    superseded_by: null,
  };

  if (previousCurrent) {
    previousCurrent.superseded_by = version;
  }

  store.template_versions.push(entry);
  return entry;
}

/**
 * Issues a template version to a client. Fails loudly if that template
 * version was never registered — a typo'd version is an error, not a
 * silent no-op. Re-issuing (e.g. a client moved from v1 to v2) is a new
 * row, not an edit — the client's issuance history stays intact.
 */
export function recordIssue(
  store: VersionStore,
  clientId: string,
  templateId: string,
  version: string,
  issuedOn: string,
): ClientVersionRecord {
  const templateExists = store.template_versions.some(
    (t) => t.template_id === templateId && t.version === version,
  );
  if (!templateExists) {
    throw new RegistryError(
      `recordIssue: no such template version "${templateId}@${version}" — register it with registerTemplateVersion first`,
    );
  }

  const entry: ClientVersionRecord = {
    client_id: clientId,
    template_id: templateId,
    version,
    issued_on: issuedOn,
    consented_on: null,
    consent_evidence: null,
  };
  store.client_versions.push(entry);
  return entry;
}

export class ConsentEvidenceRequiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConsentEvidenceRequiredError";
  }
}

/**
 * Records that a client consented to a specific issued version. This is
 * the one enforcement point for the whole store: consented_on is never set
 * without a consent_evidence reference, checked here in the writer, not
 * left to callers to remember. A consent without evidence is not a
 * consent.
 */
export function recordConsent(
  store: VersionStore,
  clientId: string,
  templateId: string,
  version: string,
  consentedOn: string,
  consentEvidence: string | null | undefined,
): ClientVersionRecord {
  if (!consentEvidence || consentEvidence.trim() === "") {
    throw new ConsentEvidenceRequiredError(
      `recordConsent: refusing to record consent for ${clientId} on ${templateId}@${version} without a consent_evidence reference — a consent without evidence is not a consent`,
    );
  }

  const record = store.client_versions.find(
    (r) =>
      r.client_id === clientId &&
      r.template_id === templateId &&
      r.version === version &&
      r.consented_on === null,
  );
  if (!record) {
    throw new RegistryError(
      `recordConsent: no pending (unconsented) issuance of ${templateId}@${version} found for ${clientId} — recordIssue must run first`,
    );
  }

  record.consented_on = consentedOn;
  record.consent_evidence = consentEvidence;
  return record;
}

/** A client's most recent issuance of a given template, by issued_on. */
export function latestClientVersion(
  store: VersionStore,
  clientId: string,
  templateId: string,
): ClientVersionRecord | null {
  const records = store.client_versions
    .filter((r) => r.client_id === clientId && r.template_id === templateId)
    .sort((a, b) => a.issued_on.localeCompare(b.issued_on));
  return records.length > 0 ? records[records.length - 1]! : null;
}

/** Every client whose most recent issuance of this template is exactly this version. */
export function clientsOnVersion(store: VersionStore, templateId: string, version: string): string[] {
  const clientIds = new Set(
    store.client_versions.filter((r) => r.template_id === templateId).map((r) => r.client_id),
  );
  const onVersion: string[] = [];
  for (const clientId of clientIds) {
    if (latestClientVersion(store, clientId, templateId)?.version === version) onVersion.push(clientId);
  }
  return onVersion.sort();
}

export type BehindReason = "outdated_version" | "not_consented" | "outdated_version_and_not_consented";

export interface BehindEntry {
  client_id: string;
  version: string;
  current_version: string;
  reason: BehindReason;
}

/**
 * A client is behind if their most recent issuance isn't the current
 * version, or if it is but they never consented to it — either way, it's
 * something a compliance officer needs to chase, not a passive fact.
 */
export function clientsBehind(store: VersionStore, templateId: string): BehindEntry[] {
  const current = currentVersion(store, templateId);
  if (!current) return [];

  const clientIds = new Set(
    store.client_versions.filter((r) => r.template_id === templateId).map((r) => r.client_id),
  );
  const behind: BehindEntry[] = [];

  for (const clientId of clientIds) {
    const latest = latestClientVersion(store, clientId, templateId);
    if (!latest) continue;

    const outdated = latest.version !== current.version;
    const notConsented = latest.consented_on === null;
    if (!outdated && !notConsented) continue;

    behind.push({
      client_id: clientId,
      version: latest.version,
      current_version: current.version,
      reason:
        outdated && notConsented
          ? "outdated_version_and_not_consented"
          : outdated
            ? "outdated_version"
            : "not_consented",
    });
  }

  return behind.sort((a, b) => a.client_id.localeCompare(b.client_id));
}
