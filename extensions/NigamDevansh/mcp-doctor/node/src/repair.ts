// The --fix run: scan, gate, back up, edit, verify, re-scan.
//
// Deliberately the only module that writes. `scan.ts` stays read-only by
// construction, so "a scan never modifies a file" is a property of the code
// layout rather than a rule someone has to remember.
//
// The order is the safety design:
//
//   scan → gate → BACK UP → edit → span-assert → re-parse → re-scan
//
// The backup happens before any byte is written, and the re-parse happens
// before the result is trusted: a fix that produces a file the client could
// not load would be a worse outcome than the defect it repaired.

import { readFileSync } from "node:fs";
import { relative, sep } from "node:path";

import { atomicReplace, writeBackup, type BackupResult } from "./backup.js";
import type { Contract } from "./contract.js";
import { planAddEntry, planFixes, repairPermitted, type FixContext } from "./fix.js";
import { parseByFormat } from "./parsers.js";
import { resolveLocation } from "./paths.js";
import { scan, type ScanOptions } from "./scan.js";
import { render as renderTemplate } from "./diagnose.js";
import type { ClientEntry, Finding, Format, Location, Report } from "./types.js";

export interface FileRepair {
  client: string;
  path: string;
  applied: { findingId: string; description: string }[];
  refused: { findingId: string; reason: string }[];
  backup?: BackupResult;
  error?: string;
}

export interface RepairResult {
  before: Report;
  after: Report;
  files: FileRepair[];
  exitCode: 0 | 1 | 2;
}

const SEVERITY_ORDER = { error: 0, warn: 1, info: 2 } as const;

/** Turn a pre-fix finding into safe, portable `--fix --json` history. */
function fixedForOutput(finding: Finding, contract: Contract, opts: ScanOptions): Finding {
  const fixed: Finding = { ...finding, fixed: true };
  if (finding.location) fixed.location = { ...finding.location };
  if (finding.data) fixed.data = { ...finding.data };
  if (!opts.deterministic) return fixed;

  const rel = (path: string) => relative(opts.cwd, path).split(sep).join("/");
  if (fixed.location?.path) fixed.location.path = rel(fixed.location.path);
  if (typeof fixed.data?.path === "string") fixed.data.path = rel(fixed.data.path);
  const defect = contract.defect(fixed.id);
  fixed.message = renderTemplate(defect.message, fixed.data ?? {});
  fixed.remediation = defect.remediation
    ? renderTemplate(defect.remediation, fixed.data ?? {})
    : null;
  return fixed;
}

/** Locate the SuperDocs entry inside a parsed document, as path segments. */
function isSuperDocsEntry(
  name: string,
  entry: Record<string, unknown>,
  client: ClientEntry,
): boolean {
  const urlField = client.http_server_schema.url.field;
  for (const rule of client.identification.rules) {
    if (rule.by === "url_host" && rule.equals) {
      const url = entry[urlField];
      if (typeof url === "string") {
        try {
          if (new URL(url).host.toLowerCase() === rule.equals.toLowerCase()) return true;
        } catch {
          // An invalid URL cannot establish an identity by host. A configured
          // name rule may still establish it below.
        }
      }
    } else if (rule.by === "name" && rule.matches) {
      if (new RegExp(rule.matches, rule.flags ?? "").test(name)) return true;
    }
  }
  return false;
}

/**
 * Find the *same* server-map shapes the scanner examines.
 *
 * A Claude user config can place a server in `projects.<name>.mcpServers`.
 * The old repair path only checked the root map, which meant scan correctly
 * found a broken project entry but --fix subsequently claimed there was
 * nothing it could act on. The scanner and writer must agree on discovery.
 */
function entryPathIn(
  value: unknown,
  client: ClientEntry,
  location: Location,
): { path: string[]; entry: Record<string, unknown> } | null {
  const doc = value as Record<string, unknown> | null;
  if (!doc || typeof doc !== "object") return null;

  const declared = location.containers?.map((c) => c.json_path) ?? [
    `$.${client.server_map.container_key}`,
  ];
  const matches: { path: string[]; entry: Record<string, unknown> }[] = [];
  const visit = (container: unknown, prefix: string[]) => {
    if (!container || typeof container !== "object" || Array.isArray(container)) return;
    for (const [name, raw] of Object.entries(container as Record<string, unknown>)) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
      const entry = raw as Record<string, unknown>;
      if (isSuperDocsEntry(name, entry, client)) matches.push({ path: [...prefix, name], entry });
    }
  };

  for (const jsonPath of declared) {
    const simple = /^\$\.([A-Za-z0-9_]+)$/.exec(jsonPath);
    if (simple) {
      visit(doc[simple[1]!], [simple[1]!]);
      continue;
    }
    const wildcard = /^\$\.([A-Za-z0-9_]+)\[\*\]\.([A-Za-z0-9_]+)$/.exec(jsonPath);
    if (!wildcard) continue;
    const outer = doc[wildcard[1]!];
    if (!outer || typeof outer !== "object" || Array.isArray(outer)) continue;
    for (const [project, raw] of Object.entries(outer as Record<string, unknown>)) {
      if (!raw || typeof raw !== "object" || Array.isArray(raw)) continue;
      visit((raw as Record<string, unknown>)[wildcard[2]!], [wildcard[1]!, project, wildcard[2]!]);
    }
  }

  // A duplicate entry has its own non-fixable finding. Refuse to choose one
  // here even if a future caller accidentally asks us to repair it.
  return matches.length === 1 ? matches[0]! : null;
}

/** A safe destination for `config.no-entry`, or null when it would be a guess. */
function addContainerPath(
  value: unknown,
  client: ClientEntry,
  location: Location,
): string[] | null {
  const doc = value as Record<string, unknown> | null;
  if (!doc || typeof doc !== "object" || Array.isArray(doc)) return null;
  const declared = location.containers?.map((c) => c.json_path) ?? [
    `$.${client.server_map.container_key}`,
  ];
  // A wildcard is a project-specific decision. Do not install a server in one
  // project merely because several were discovered in the same user file.
  const simple = declared
    .map((path) => /^\$\.([A-Za-z0-9_]+)$/.exec(path)?.[1])
    .filter((key): key is string => Boolean(key));
  if (simple.length !== 1) return null;
  const key = simple[0]!;
  const existing = doc[key];
  if (existing !== undefined && (typeof existing !== "object" || existing === null || Array.isArray(existing))) {
    return null;
  }
  return [key];
}

export function repair(contract: Contract, opts: ScanOptions): RepairResult {
  // Source paths are needed to associate findings with the file to edit. The
  // public report can still be deterministic, but relativising before the
  // repair association would make every comparison fail under fixture mode.
  const workOpts = { ...opts, deterministic: false };
  const before = scan(contract, workOpts);
  const files: FileRepair[] = [];

  const selected = opts.clientFilter
    ? contract.clients.filter((c) => c.id === opts.clientFilter)
    : contract.clients;

  for (const client of selected) {
    const seen = new Set<string>();

    for (const location of [...client.locations].sort((a, b) => a.precedence - b.precedence)) {
      let target: string | null;
      if (opts.singleFile) {
        if (!opts.singleFile.endsWith(location.path.split("/").pop()!)) continue;
        target = opts.singleFile;
      } else {
        target = resolveLocation(location, contract.bases, {
          os: opts.os,
          cwd: opts.cwd,
          env: opts.env,
        }).path;
      }
      if (!target) continue;
      if (seen.has(target)) continue;
      seen.add(target);

      const forThisFile = before.findings.filter(
        (f) => f.client === client.name && f.location?.path === target,
      );
      const fixable = forThisFile.filter((f) => {
        const d = contract.defect(f.id);
        return d.auto_fixable && d.fix_kind;
      });
      if (fixable.length === 0) continue;

      const record: FileRepair = { client: client.name, path: target, applied: [], refused: [] };

      // Gate first: if nothing is permitted, do not even open the file for
      // writing — and certainly do not leave a backup behind.
      const anyPermitted = fixable.some((f) => {
        const kind = contract.defect(f.id).fix_kind!;
        return repairPermitted(client, kind, opts.os).ok;
      });
      if (!anyPermitted) {
        for (const f of fixable) {
          const kind = contract.defect(f.id).fix_kind!;
          const verdict = repairPermitted(client, kind, opts.os);
          if (!verdict.ok) record.refused.push({ findingId: f.id, reason: verdict.reason });
        }
        files.push(record);
        continue;
      }

      let text: string;
      try {
        text = readFileSync(target, "utf8");
      } catch (err) {
        record.error = `could not read: ${(err as Error).message}`;
        files.push(record);
        continue;
      }

      const format = location.format as Format;
      const parsed = parseByFormat(text, format);
      if (!parsed.ok) {
        // Never rewrite a file we could not parse — repairing it would mean
        // guessing at its structure.
        record.error = "not repaired: the file could not be parsed";
        files.push(record);
        continue;
      }

      const located = entryPathIn(parsed.root.value, client, location);
      const outcome = located
        ? planFixes(
          fixable,
          {
            contract,
            client,
            os: opts.os,
            format,
            entryPath: located.path,
            entry: located.entry,
            key: opts.env[opts.keyEnvVar],
          } satisfies FixContext,
          text,
        )
        : (() => {
          const containerPath = addContainerPath(parsed.root.value, client, location);
          if (!containerPath) {
            return {
              text,
              applied: [],
              refused: [],
              error: "not repaired: no unambiguous registry-approved container to add a SuperDocs entry",
            };
          }
          return planAddEntry(fixable, {
            contract,
            client,
            os: opts.os,
            format,
            containerPath,
            key: opts.env[opts.keyEnvVar],
          }, text);
        })();
      if (outcome.error) {
        record.error = outcome.error;
        files.push(record);
        continue;
      }
      record.refused.push(...outcome.refused);

      if (outcome.applied.length === 0) {
        files.push(record);
        continue;
      }

      // The repaired text must still parse. Writing a file the client cannot
      // load would be worse than the defect we set out to fix.
      const reparsed = parseByFormat(outcome.text, format);
      if (!reparsed.ok) {
        record.error = "not written: the repaired file did not parse";
        files.push(record);
        continue;
      }

      try {
        record.backup = writeBackup(target, text);
        atomicReplace(target, outcome.text);
      } catch (err) {
        record.error = `could not write: ${(err as Error).message}`;
        files.push(record);
        continue;
      }

      record.applied = outcome.applied.map((a) => ({
        findingId: a.findingId,
        description: a.description,
      }));
      files.push(record);
    }
  }

  const after = scan(contract, opts);
  const fixedHistory = before.findings.filter((finding) =>
    files.some(
      (file) =>
        file.client === finding.client &&
        file.path === finding.location?.path &&
        file.applied.some((applied) => applied.findingId === finding.id),
    ),
  );
  after.findings.push(...fixedHistory.map((finding) => fixedForOutput(finding, contract, opts)));
  after.findings.sort(
    (a, b) =>
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.id.localeCompare(b.id) ||
      (a.location?.path ?? "").localeCompare(b.location?.path ?? ""),
  );
  after.summary.fixed = fixedHistory.length;
  const errors = after.summary.errors;
  const needsManual = files.some((f) => f.error || f.refused.length > 0);
  return { before, after, files, exitCode: needsManual || errors > 0 ? 1 : 0 };
}
