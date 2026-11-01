import { createHash } from "node:crypto";
import { existsSync, readFileSync, mkdirSync, writeFileSync, renameSync } from "node:fs";
import { join } from "node:path";
import type { TermCandidate } from "../types.js";

export interface MemoryEntry {
  canonicalForm: string;
  category: TermCandidate["category"];
  policy: TermCandidate["suggestedPolicy"];
  meaning: string;
  pronunciation: string | null;
  approvedAt: string;
}

function scopeId(title: string | null, author: string | null, targetLanguage: string): string {
  return createHash("sha256").update(`${title ?? "untitled"}\n${author ?? "unknown"}\n${targetLanguage}`.toLowerCase()).digest("hex").slice(0, 16);
}

export class TermMemory {
  private readonly file: string;
  private readonly entries = new Map<string, MemoryEntry[]>();

  constructor(root = join(process.cwd(), "run-artifacts")) {
    mkdirSync(root, { recursive: true });
    this.file = join(root, "term-memory.json");
    if (existsSync(this.file)) {
      try {
        const parsed = JSON.parse(readFileSync(this.file, "utf8")) as Record<string, MemoryEntry[]>;
        for (const [key, value] of Object.entries(parsed)) if (Array.isArray(value)) this.entries.set(key, value);
      } catch {
        // Corrupt memory must never block manuscript processing; it is treated as empty and replaced on next write.
      }
    }
  }

  suggestions(title: string | null, author: string | null, targetLanguage: string): MemoryEntry[] {
    return [...(this.entries.get(scopeId(title, author, targetLanguage)) ?? [])];
  }

  remember(title: string | null, author: string | null, targetLanguage: string, terms: TermCandidate[]): void {
    const key = scopeId(title, author, targetLanguage);
    const existing = new Map((this.entries.get(key) ?? []).map((entry) => [entry.canonicalForm.toLocaleLowerCase(), entry]));
    for (const term of terms.filter((t) => t.status === "confirmed")) {
      const canonical = term.confirmedOverride?.canonicalForm ?? term.canonicalForm;
      existing.set(canonical.toLocaleLowerCase(), {
        canonicalForm: canonical,
        category: term.category,
        policy: term.confirmedOverride?.policy ?? term.suggestedPolicy,
        meaning: term.meaning,
        pronunciation: term.pronunciation.value,
        approvedAt: term.reviewedAt ?? new Date().toISOString(),
      });
    }
    this.entries.set(key, [...existing.values()].sort((a, b) => a.canonicalForm.localeCompare(b.canonicalForm)));
    const serialized = Object.fromEntries(this.entries.entries());
    const tempFile = `${this.file}.tmp`;
    writeFileSync(tempFile, JSON.stringify(serialized, null, 2));
    renameSync(tempFile, this.file);
  }
}
