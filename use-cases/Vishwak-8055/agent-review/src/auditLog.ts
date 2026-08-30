import type { PersistenceBackend } from "./persistence";
import type { AuditRecord } from "./types";

const PREFIX = "audit:";
const INDEX_KEY = "audit-index"; // ordered list of record ids, oldest first

/**
 * Append-only. There is no `update` or `delete` on this class by design —
 * later actions on the same Change (approve, then later revert) write a
 * *new* AuditRecord rather than mutating the old one, so the trail can
 * never be quietly edited after the fact.
 */
export class AuditLog {
  constructor(private readonly backend: PersistenceBackend) {}

  append(record: AuditRecord): void {
    this.backend.set(`${PREFIX}${record.id}`, record);
    const index = this.backend.get<string[]>(INDEX_KEY) ?? [];
    index.push(record.id);
    this.backend.set(INDEX_KEY, index);
  }

  all(): AuditRecord[] {
    const index = this.backend.get<string[]>(INDEX_KEY) ?? [];
    return index
      .map((id) => this.backend.get<AuditRecord>(`${PREFIX}${id}`))
      .filter((r): r is AuditRecord => r !== undefined);
  }

  forChange(changeId: string): AuditRecord[] {
    return this.all().filter((r) => r.changeId === changeId);
  }

  forTurn(turnId: string): AuditRecord[] {
    return this.all().filter((r) => r.turnId === turnId);
  }
}

let auditIdCounter = 0;
/**
 * Monotonic-enough id for a single extension-host process; collisions across
 * restarts are avoided by prefixing with the timestamp.
 */
export function nextAuditId(now: () => string = () => new Date().toISOString()): string {
  auditIdCounter += 1;
  return `audit_${now()}_${auditIdCounter}`;
}
