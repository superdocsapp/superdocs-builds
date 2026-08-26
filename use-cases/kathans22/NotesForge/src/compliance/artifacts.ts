import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { OpsLedger } from "../budget.js";
import type { CoverageEntry, CoverageStatus } from "./coverage.js";
import type { CompliancePackDraft } from "./generate.js";

export const DEFAULT_COVERAGE_PATH = fileURLToPath(new URL("../../state/coverage.json", import.meta.url));
export const DEFAULT_PACKS_PATH = fileURLToPath(new URL("../../state/packs.json", import.meta.url));
export const DEFAULT_LEDGER_PATH = fileURLToPath(new URL("../../state/ledger.json", import.meta.url));

async function writeJson(filePath: string, data: unknown): Promise<void> {
  await mkdir(path.dirname(filePath), { recursive: true });
  await writeFile(filePath, `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

/**
 * Persists assessCoverage's output exactly as computed — no re-derivation.
 * Same idiom as --matrix already writing state/consent-matrix.json: turn an
 * in-memory result the CLI already trusted into a read artifact.
 */
export async function writeCoverageSnapshot(
  entries: CoverageEntry[],
  notesDir: string,
  filePath: string = DEFAULT_COVERAGE_PATH,
): Promise<void> {
  const summary: Record<CoverageStatus, number> = { EVIDENCED: 0, STALE: 0, MISSING: 0, INCONSISTENT: 0 };
  for (const e of entries) summary[e.status]++;

  await writeJson(filePath, {
    generated_at: new Date().toISOString(),
    notes_dir: notesDir,
    summary,
    entries,
  });
}

export interface PackManifestEntry {
  client_id: string;
  client_name: string;
  title: string;
  documentId: string;
  durableDocumentId: string | null;
  sessionId: string;
  verified: boolean;
  plannedSections: CompliancePackDraft["plannedSections"];
  exportedFiles: string[];
  generated_at: string;
}

/** Missing manifest means --generate has never run — not an error. */
export async function loadPacksManifest(filePath: string = DEFAULT_PACKS_PATH): Promise<PackManifestEntry[]> {
  try {
    const text = await readFile(filePath, "utf8");
    return (JSON.parse(text) as { packs: PackManifestEntry[] }).packs;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw err;
  }
}

/**
 * Merges freshly generated entries into whatever manifest is already on
 * disk, keyed by client_id — a --clients-scoped run must not erase the
 * packs recorded for clients it didn't touch this time.
 */
export async function writePacksManifest(
  freshPacks: PackManifestEntry[],
  filePath: string = DEFAULT_PACKS_PATH,
): Promise<void> {
  const existing = await loadPacksManifest(filePath);
  const freshIds = new Set(freshPacks.map((p) => p.client_id));
  const merged = [...existing.filter((p) => !freshIds.has(p.client_id)), ...freshPacks];
  await writeJson(filePath, { generated_at: new Date().toISOString(), packs: merged });
}

export interface LedgerSnapshotRow {
  label: string;
  opsCharged: number;
  runningTotal: number;
  monthlyRemaining: number | null;
}

/**
 * Snapshots an OpsLedger's own rows (ledger.snapshot) after a compliance
 * command finishes — never recomputed, just written to disk so the UI can
 * read the same numbers the CLI already printed via ledger.report().
 */
export async function writeLedgerSnapshot(
  command: string,
  ledger: OpsLedger,
  opsCap: number,
  filePath: string = DEFAULT_LEDGER_PATH,
): Promise<void> {
  await writeJson(filePath, {
    command,
    generated_at: new Date().toISOString(),
    ops_cap: opsCap,
    total_spent: ledger.spent,
    remaining: ledger.remaining,
    rows: ledger.snapshot,
  });
}
