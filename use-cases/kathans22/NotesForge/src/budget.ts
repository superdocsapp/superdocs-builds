import { CONFIG } from "./config.js";
import type { Logger } from "./logger.js";
import type { UsageBlock } from "./types.js";

export class BudgetExceededError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BudgetExceededError";
  }
}

interface LedgerRow {
  label: string;
  opsCharged: number;
  runningTotal: number;
  monthlyRemaining: number | null;
}

export class OpsLedger {
  private readonly rows: LedgerRow[] = [];
  private totalSpent = 0;
  private lastRemaining: number | null = null;

  constructor(
    private readonly logger: Logger,
    private readonly opsCap: number = CONFIG.OPS_CAP,
  ) {}

  record(label: string, usage?: UsageBlock | null): void {
    const opsCharged = usage?.ops_charged ?? 0;
    this.totalSpent += opsCharged;
    if (usage?.monthly_remaining != null) {
      this.lastRemaining = usage.monthly_remaining;
    }

    this.rows.push({
      label,
      opsCharged,
      runningTotal: this.totalSpent,
      monthlyRemaining: this.lastRemaining,
    });

    if (opsCharged === 0) {
      this.logger.info(`${label}: free read (0 ops)`);
    } else {
      this.logger.info(
        `${label}: ${opsCharged} op(s) charged — ${this.totalSpent} total this run`,
      );
    }

    if (usage?.quota_exhausted) {
      this.logger.warn(
        `quota exhausted — this request still completed, but further billable requests will pause until the billing cycle resets or the account is upgraded`,
      );
    }
  }

  get spent(): number {
    return this.totalSpent;
  }

  get remaining(): number | null {
    return this.lastRemaining;
  }

  /** The rows this ledger has recorded so far — read-only, for persisting a run snapshot. */
  get snapshot(): readonly LedgerRow[] {
    return this.rows;
  }

  assertCanSpend(estimate: number): void {
    if (this.totalSpent + estimate > this.opsCap) {
      throw new BudgetExceededError(
        `spending ~${estimate} more op(s) would exceed the ${this.opsCap}-op cap for this run (${this.totalSpent} already spent) — aborting`,
      );
    }
  }

  report(): string {
    if (this.rows.length === 0) {
      return "(no ops recorded this run)";
    }
    const header = ["step", "ops charged", "running total", "monthly remaining after"];
    const rows = this.rows.map((r) => [
      r.label,
      String(r.opsCharged),
      String(r.runningTotal),
      r.monthlyRemaining === null ? "?" : String(r.monthlyRemaining),
    ]);
    const widths = header.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i]!.length)));
    const formatRow = (cols: string[]) => cols.map((c, i) => c.padEnd(widths[i]!)).join("  ");
    return [formatRow(header), widths.map((w) => "-".repeat(w)).join("  "), ...rows.map(formatRow)].join(
      "\n",
    );
  }
}
