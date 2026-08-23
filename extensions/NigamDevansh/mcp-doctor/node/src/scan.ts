// Discovery and the scan report.
//
// Read-only by construction: this module opens files and never writes one.

import { readFileSync, statSync } from "node:fs";
import { relative, sep } from "node:path";
import type { Contract } from "./contract.js";
import {
  diagnoseEntry,
  finding,
  render as renderTemplate,
  summariseEntry,
  type EntryContext,
} from "./diagnose.js";
import { parseByFormat, type ParsedNode } from "./parsers.js";
import { currentOs, resolveLocation, type ResolveOptions } from "./paths.js";
import type {
  ClientEntry,
  ClientReport,
  ConfigFileReport,
  EvidenceTier,
  Finding,
  Location,
  OsName,
  Report,
} from "./types.js";

export const VERSION = "0.1.0";
const SEVERITY_ORDER = { error: 0, warn: 1, info: 2 } as const;

export interface ScanOptions {
  cwd: string;
  env: NodeJS.ProcessEnv;
  os: OsName;
  clientFilter?: string;
  /** --config: diagnose exactly this file, instead of the registry's locations. */
  singleFile?: string;
  keyEnvVar: string;
  deterministic: boolean;
}

export function defaultOptions(env: NodeJS.ProcessEnv = process.env): ScanOptions {
  const os = currentOs();
  if (!os) throw new Error(`unsupported platform: ${process.platform}`);
  return {
    cwd: process.cwd(),
    env,
    os,
    keyEnvVar: env.MCP_DOCTOR_KEY_ENV ?? "SUPERDOCS_API_KEY",
    deterministic: env.MCP_DOCTOR_DETERMINISTIC === "1",
  };
}

interface Container {
  raw: Record<string, unknown>;
  /** Where it came from, so a finding can point at the right place. */
  jsonPath: string;
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

/**
 * Every server map in a document, per the registry's declared `containers`.
 *
 * Claude Code keeps MCP servers in TWO places: the top-level `mcpServers` and
 * a per-project `projects["/path"].mcpServers`. Reading only the first reports
 * "no SuperDocs server configured" while a perfectly good one sits in the
 * project block — so the declared paths are honoured rather than assumed.
 *
 * Supported json_path shapes are exactly the two the registry uses:
 *   $.key            and   $.key[*].key
 */
function containersOf(root: ParsedNode, client: ClientEntry, location: Location): Container[] {
  const doc = asObject(root.value);
  if (!doc) return [];

  const declared = location.containers?.map((c) => c.json_path) ?? [
    `$.${client.server_map.container_key}`,
  ];
  const found: Container[] = [];

  for (const jsonPath of declared) {
    const wildcard = /^\$\.([A-Za-z0-9_]+)\[\*\]\.([A-Za-z0-9_]+)$/.exec(jsonPath);
    if (wildcard) {
      const [, outerKey, innerKey] = wildcard;
      const outer = asObject(doc[outerKey!]);
      if (!outer) continue;
      for (const [name, entry] of Object.entries(outer)) {
        const inner = asObject(asObject(entry)?.[innerKey!]);
        if (inner) found.push({ raw: inner, jsonPath: `$.${outerKey}["${name}"].${innerKey}` });
      }
      continue;
    }
    const simple = /^\$\.([A-Za-z0-9_]+)$/.exec(jsonPath);
    if (simple) {
      const value = asObject(doc[simple[1]!]);
      if (value) found.push({ raw: value, jsonPath });
    }
  }

  return found;
}

/** Which entries look like SuperDocs, per the registry's identification rules. */
function identify(container: Container, client: ClientEntry): EntryContext[] {
  const found: EntryContext[] = [];
  const urlField = client.http_server_schema.url.field;

  for (const [name, value] of Object.entries(container.raw)) {
    if (typeof value !== "object" || value === null) continue;
    const raw = value as Record<string, unknown>;

    let matched = false;
    for (const rule of client.identification.rules) {
      if (rule.by === "url_host" && rule.equals) {
        const url = raw[urlField];
        if (typeof url === "string") {
          try {
            if (new URL(url).host.toLowerCase() === rule.equals.toLowerCase()) matched = true;
          } catch {
            /* an unparseable URL simply does not match this rule */
          }
        }
      } else if (rule.by === "name" && rule.matches) {
        // Flags come from a separate field: an inline `(?i)` group is
        // Python-only syntax and throws here. The validator forbids it.
        if (new RegExp(rule.matches, rule.flags ?? "").test(name)) matched = true;
      }
      if (matched) break;
    }

    if (matched) {
      found.push({ name, raw, jsonPath: `${container.jsonPath}.${name}` });
    }
  }
  return found;
}

function analyseFile(
  contract: Contract,
  client: ClientEntry,
  location: Location,
  path: string,
  opts: ScanOptions,
): { report: ConfigFileReport; findings: Finding[] } {
  const base = { path, scope: location.scope, format: location.format } as const;
  const findings: Finding[] = [];
  const ctx = { client: client.name, path };

  let text: string;
  try {
    if (!statSync(path).isFile()) {
      return { report: { ...base, status: "absent" }, findings };
    }
    text = readFileSync(path, "utf8");
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ENOENT") return { report: { ...base, status: "absent" }, findings };
    findings.push(
      finding(
        contract.defect("config.file-unreadable"),
        { ...ctx, reason: code ?? "unreadable" },
        { client: client.name, location: { path } },
      ),
    );
    return { report: { ...base, status: "unreadable" }, findings };
  }

  const parsed = parseByFormat(text, location.format);

  if (!parsed.ok) {
    // An empty file is NOT a corrupt one — reporting "invalid JSON at 1:1"
    // would send someone hunting for damage that is not there.
    if (parsed.empty) {
      findings.push(
        finding(contract.defect("config.file-empty"), ctx, {
          client: client.name,
          location: { path },
        }),
      );
      return { report: { ...base, status: "ok", entries: [] }, findings };
    }
    findings.push(
      finding(
        contract.defect("config.invalid-syntax"),
        {
          ...ctx,
          format: location.format.toUpperCase(),
          line: parsed.line ?? 1,
          column: parsed.column ?? 1,
          reason: parsed.reason,
        },
        {
          client: client.name,
          location: { path, line: parsed.line, column: parsed.column },
        },
      ),
    );
    return { report: { ...base, status: "invalid" }, findings };
  }

  // A repeated key is not a syntax error — JSON keeps the last silently, so a
  // stale value above a good one looks like a working config that does not work.
  for (const dup of parsed.duplicates) {
    findings.push(
      finding(
        contract.defect("config.duplicate-keys"),
        { ...ctx, field_name: dup.key, container: dup.container },
        { client: client.name, location: { path, json_path: `$.${dup.container}` } },
      ),
    );
  }

  const entries = containersOf(parsed.root, client, location).flatMap((c) => identify(c, client));

  if (entries.length === 0) {
    findings.push(
      finding(
        contract.defect("config.no-entry"),
        { ...ctx, key_env: opts.keyEnvVar },
        { client: client.name, location: { path } },
      ),
    );
    return { report: { ...base, status: "ok", entries: [] }, findings };
  }

  if (entries.length > 1) {
    // Never guess which to keep — and stop here, because diagnosing one of an
    // ambiguous pair would attribute findings to an entry we did not choose.
    findings.push(
      finding(
        contract.defect("config.duplicate-entries"),
        { ...ctx, count: entries.length, names: entries.map((e) => e.name).join(", ") },
        { client: client.name, location: { path } },
      ),
    );
    return {
      report: {
        ...base,
        status: "ok",
        entries: entries.map((e) => summariseEntry(e, client, contract.profile)),
      },
      findings,
    };
  }

  for (const entry of entries) {
    findings.push(
      ...diagnoseEntry(
        {
          contract,
          client,
          filePath: path,
          entries,
          env: opts.env,
          keyEnvVar: opts.keyEnvVar,
        },
        entry,
      ),
    );
  }

  return {
    report: {
      ...base,
      status: "ok",
      entries: entries.map((e) => summariseEntry(e, client, contract.profile)),
    },
    findings,
  };
}

function evidenceTier(client: ClientEntry, os: OsName): EvidenceTier {
  const order: EvidenceTier[] = ["unverified", "documented", "captured"];
  const pathTier = client.evidence.paths[os]?.status ?? "unverified";
  const schemaTier = client.evidence.schema.status;
  // The weaker of the two: knowing where the file is does not mean knowing
  // what belongs inside it.
  return order[Math.min(order.indexOf(pathTier), order.indexOf(schemaTier))]!;
}

export function scan(contract: Contract, opts: ScanOptions): Report {
  const resolveOpts: ResolveOptions = { os: opts.os, cwd: opts.cwd, env: opts.env };
  const clients: ClientReport[] = [];
  const findings: Finding[] = [];
  let filesRead = 0;
  let entriesFound = 0;

  const selected = opts.clientFilter
    ? contract.clients.filter((c) => c.id === opts.clientFilter)
    : contract.clients;

  for (const client of selected) {
    const files: ConfigFileReport[] = [];
    const locations = [...client.locations].sort((a, b) => a.precedence - b.precedence);

    const seen = new Set<string>();

    for (const location of locations) {
      // --config pins the file; the location still supplies the format and the
      // container paths, which is why it is matched rather than bypassed.
      let target: string | null;
      if (opts.singleFile) {
        const leaf = location.path.split("/").pop()!;
        if (!opts.singleFile.endsWith(leaf)) continue;
        target = opts.singleFile;
      } else {
        const resolved = resolveLocation(location, contract.bases, resolveOpts);
        target = resolved.path; // null: unresolvable on this OS — not a fault
      }
      if (!target) continue;
      if (seen.has(target)) continue;
      seen.add(target);

      const { report, findings: fileFindings } = analyseFile(
        contract,
        client,
        location,
        target,
        opts,
      );
      files.push(report);
      findings.push(...fileFindings);
      if (report.status !== "absent") filesRead++;
      entriesFound += report.entries?.length ?? 0;
    }

    clients.push({
      id: client.id,
      name: client.name,
      write_capable: client.write_capable[opts.os] ?? false,
      evidence_tier: evidenceTier(client, opts.os),
      // `locations` was ordered by its registry precedence above.  Retaining
      // that order is both the useful answer (which config wins?) and part of
      // the JSON wire contract.  Sorting scope labels here made user appear
      // ahead of workspace in Node while Python retained declared precedence.
      config_files: files,
    });
  }

  // Deterministic mode: paths relative to the scan root, forward slashes.
  //
  // Required by the shared --json contract. Without it the conformance suite
  // compares /var/folders/T/xyz/... against /tmp/abc/... and every case fails
  // for reasons that have nothing to do with either implementation.
  if (opts.deterministic) {
    const rel = (p: string) => relative(opts.cwd, p).split(sep).join("/");
    for (const client of clients) {
      for (const file of client.config_files) file.path = rel(file.path);
    }
    for (const f of findings) {
      if (f.location?.path) f.location.path = rel(f.location.path);
      if (typeof f.data?.path === "string") f.data.path = rel(f.data.path);
      // The message was rendered from `data`, so re-render it against the
      // relativised values rather than leaving an absolute path inside it.
      const defect = contract.defect(f.id);
      f.message = renderTemplate(defect.message, f.data ?? {});
      f.remediation = defect.remediation
        ? renderTemplate(defect.remediation, f.data ?? {})
        : null;
    }
  }

  // Deterministic ordering — the conformance suite compares byte-for-byte.
  findings.sort(
    (a, b) =>
      SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] ||
      a.id.localeCompare(b.id) ||
      (a.location?.path ?? "").localeCompare(b.location?.path ?? ""),
  );

  const errors = findings.filter((f) => f.severity === "error").length;
  const warnings = findings.filter((f) => f.severity === "warn").length;

  const report: Report = {
    schema_version: 1,
    tool: {
      name: "mcp-doctor",
      version: opts.deterministic ? "deterministic" : VERSION,
      implementation: "typescript",
    },
    summary: {
      clients_scanned: clients.length,
      config_files_read: filesRead,
      entries_found: entriesFound,
      errors,
      warnings,
      fixed: 0,
      connection: "not-attempted",
    },
    clients,
    findings,
    exit_code: errors > 0 ? 1 : 0,
  };

  if (!opts.deterministic) report.generated_at = new Date().toISOString();
  return report;
}
