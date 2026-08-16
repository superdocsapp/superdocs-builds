import { promises as fs } from "node:fs";

export interface SuperDocsUsage {
  monthlyUsed?: number;
  monthlyLimit?: number;
  monthlyRemaining?: number;
  wasBillable?: boolean;
  operationsCharged?: number;
  subscriptionTier?: string;
}

export interface UsageRecord extends SuperDocsUsage {
  recordedAt: string;
  operation: "chat" | "async-chat" | "job";
  sessionId?: string;
  jobId?: string;
}

export interface UsageLedger {
  records: UsageRecord[];
}

export async function appendUsageRecord(path: string, record: UsageRecord): Promise<void> {
  const lockPath = `${path}.lock`;
  let lock;
  for (let attempt = 0; attempt < 20; attempt += 1) {
    try {
      lock = await fs.open(lockPath, "wx");
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 25));
    }
  }
  if (!lock) throw new Error(`Unable to lock usage ledger: ${path}`);

  try {
    const ledger = await readUsageLedger(path);
    ledger.records.push(record);
    const temporaryPath = `${path}.tmp-${process.pid}-${Date.now()}`;
    await fs.writeFile(temporaryPath, JSON.stringify(ledger, null, 2), "utf8");
    await fs.rename(temporaryPath, path);
  } finally {
    await lock.close();
    await fs.rm(lockPath, { force: true });
  }
}

export async function readUsageLedger(path: string): Promise<UsageLedger> {
  try {
    const parsed = JSON.parse(await fs.readFile(path, "utf8")) as UsageLedger;
    return Array.isArray(parsed.records) ? parsed : { records: [] };
  } catch {
    return { records: [] };
  }
}

export function summarizeUsage(ledger: UsageLedger): {
  recordCount: number;
  billableRecords: number;
  operationsCharged: number;
  latest?: UsageRecord;
} {
  return {
    recordCount: ledger.records.length,
    billableRecords: ledger.records.filter((record) => record.wasBillable).length,
    operationsCharged: ledger.records.reduce((total, record) => total + (record.operationsCharged ?? 0), 0),
    latest: ledger.records.at(-1),
  };
}

export function usageFromApi(value: unknown): SuperDocsUsage | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const raw = value as Record<string, unknown>;
  const usage: SuperDocsUsage = {
    monthlyUsed: numberOrUndefined(raw.monthly_used),
    monthlyLimit: numberOrUndefined(raw.monthly_limit),
    monthlyRemaining: numberOrUndefined(raw.monthly_remaining),
    wasBillable: booleanOrUndefined(raw.was_billable),
    operationsCharged: numberOrUndefined(raw.ops_charged),
    subscriptionTier: stringOrUndefined(raw.subscription_tier),
  };
  return Object.values(usage).some((item) => item !== undefined) ? usage : undefined;
}

function numberOrUndefined(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function booleanOrUndefined(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function stringOrUndefined(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}
