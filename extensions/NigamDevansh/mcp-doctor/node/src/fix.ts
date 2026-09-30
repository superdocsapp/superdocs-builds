// Turning findings into edits.
//
// Two gates stand between a finding and a byte being written:
//
//   1. the DEFECT must be auto_fixable, and
//   2. the CLIENT must permit that fix_kind AND be write-capable on this OS.
//
// Both come from shared/. Neither is a judgement made here, which is what
// keeps TypeScript and Python doing the same thing.
//
// Nothing in the `scope` class is ever fixable — that is the host rule, and it
// is enforced in the contract rather than remembered here.

import type { Contract } from "./contract.js";
import {
  applyJsonEdits,
  applyTextEdits,
  assertOnlySpansChanged,
  jsonEdits,
  tomlValueEdit,
  type TextEdit,
} from "./edits.js";
import { parseByFormat } from "./parsers.js";
import type { ClientEntry, Finding, Format, OsName } from "./types.js";

export interface FixContext {
  contract: Contract;
  client: ClientEntry;
  os: OsName;
  format: Format;
  /** Path segments to the SuperDocs entry, e.g. ["mcpServers", "superdocs"]. */
  entryPath: string[];
  entry: Record<string, unknown>;
  /** Resolved credential, when one is available. Never invented. */
  key?: string;
}

export interface PlannedFix {
  findingId: string;
  fixKind: string;
  description: string;
  edits: TextEdit[];
}

export interface FixOutcome {
  text: string;
  applied: PlannedFix[];
  /** Fixable in principle, but refused here — with the reason. */
  refused: { findingId: string; reason: string }[];
  error?: string;
}

export interface AddEntryContext {
  contract: Contract;
  client: ClientEntry;
  os: OsName;
  format: Format;
  /** A registry-declared server map, e.g. ["mcpServers"]. */
  containerPath: string[];
  /** Resolved credential. Absence is a manual-action result, never a guess. */
  key?: string;
}

/** Is this client allowed to perform this kind of repair, on this OS? */
export function repairPermitted(
  client: ClientEntry,
  fixKind: string,
  os: OsName,
): { ok: true } | { ok: false; reason: string } {
  if (!client.write_capable[os]) {
    const tier = client.evidence.schema.status;
    return {
      ok: false,
      reason:
        `${client.name} is not write-capable on ${os}: its configuration knowledge ` +
        `is '${tier}', not captured from a real installation`,
    };
  }
  if (!client.repairs.allowed.includes(fixKind)) {
    return { ok: false, reason: `${client.name} does not permit the '${fixKind}' repair` };
  }
  return { ok: true };
}

function headerKeyFor(entry: Record<string, unknown>, client: ClientEntry, wanted: string): string {
  const field = client.http_server_schema.headers.field;
  const headers = field ? entry[field] : undefined;
  if (typeof headers === "object" && headers !== null) {
    for (const k of Object.keys(headers as Record<string, unknown>)) {
      if (k.toLowerCase() === wanted.toLowerCase()) return k; // keep their casing
    }
  }
  return wanted;
}

function currentUrl(entry: Record<string, unknown>, client: ClientEntry): string | null {
  const value = entry[client.http_server_schema.url.field];
  return typeof value === "string" ? value : null;
}

/**
 * The new value a finding implies, as a (path, value) pair.
 * Returns null when this finding does not map to a single value change.
 */
function targetFor(
  finding: Finding,
  ctx: FixContext,
): { path: string[]; value: unknown; description: string } | null {
  const { client, entry, contract } = ctx;
  const profile = contract.profile;
  const schema = client.http_server_schema;
  const urlField = schema.url.field;
  const headersField = schema.headers.field ?? "headers";
  const authName = schema.headers.authorization_header ?? "Authorization";
  const acceptName = schema.headers.accept_header ?? "Accept";
  const scheme = profile.credential.header_scheme;

  switch (finding.id) {
    case "config.scheme-insecure": {
      const url = currentUrl(entry, client);
      if (!url) return null;
      const next = new URL(url);
      next.protocol = `${profile.canonical.scheme}:`;
      return {
        path: [...ctx.entryPath, urlField],
        value: next.toString(),
        description: "use https://",
      };
    }
    case "config.path-wrong": {
      const url = currentUrl(entry, client);
      if (!url) return null;
      const next = new URL(url);
      next.pathname = profile.canonical.path;
      return {
        path: [...ctx.entryPath, urlField],
        value: next.toString(),
        description: `set the path to ${profile.canonical.path}`,
      };
    }
    case "config.transport-not-http": {
      const field = schema.transport.field;
      if (!field || !schema.transport.preferred) return null;
      return {
        path: [...ctx.entryPath, field],
        value: schema.transport.preferred,
        description: `set ${field} to ${schema.transport.preferred}`,
      };
    }
    case "config.auth-header-no-bearer": {
      const key = headerKeyFor(entry, client, authName);
      const headers = entry[headersField] as Record<string, unknown> | undefined;
      const value = String(headers?.[key] ?? "").trim();
      return {
        path: [...ctx.entryPath, headersField, key],
        value: `${scheme} ${value}`,
        description: `prefix the ${authName} value with ${scheme}`,
      };
    }
    case "config.auth-header-doubled-bearer": {
      const key = headerKeyFor(entry, client, authName);
      const headers = entry[headersField] as Record<string, unknown> | undefined;
      const value = String(headers?.[key] ?? "").trim();
      const collapsed = value.replace(
        new RegExp(`^(?:${scheme}\\s+)+`, "i"),
        `${scheme} `,
      );
      return {
        path: [...ctx.entryPath, headersField, key],
        value: collapsed,
        description: `write ${scheme} once`,
      };
    }
    case "config.auth-header-missing": {
      // The key comes from the environment and is NEVER invented.
      if (!ctx.key) return null;
      return {
        path: [...ctx.entryPath, headersField, authName],
        value: `${scheme} ${ctx.key}`,
        description: `add the ${authName} header`,
      };
    }
    case "config.accept-header-incompatible": {
      const key = headerKeyFor(entry, client, acceptName);
      return {
        path: [...ctx.entryPath, headersField, key],
        value: profile.accept_header.must_include,
        description: `set ${acceptName} to ${profile.accept_header.must_include}`,
      };
    }
    default:
      return null;
  }
}

/** Path segments → the TOML (table, key) the value lives in. */
function tomlTargetFor(path: string[]): { table: string; key: string } | null {
  // ["mcp_servers","superdocs","url"]                  → [mcp_servers.superdocs] url
  // ["mcp_servers","superdocs","http_headers","Authorization"]
  //                                                    → [mcp_servers.superdocs.http_headers] Authorization
  if (path.length < 3) return null;
  return { table: path.slice(0, -1).join("."), key: path[path.length - 1]! };
}

/** Walk path segments through a parsed document. */
function entryAt(value: unknown, path: string[]): Record<string, unknown> | null {
  let node: unknown = value;
  for (const segment of path) {
    if (typeof node !== "object" || node === null) return null;
    node = (node as Record<string, unknown>)[segment];
  }
  return typeof node === "object" && node !== null ? (node as Record<string, unknown>) : null;
}

export function planFixes(findings: Finding[], ctx: FixContext, text: string): FixOutcome {
  const applied: PlannedFix[] = [];
  const refused: { findingId: string; reason: string }[] = [];
  let working = text;

  // `entry` is re-read after every applied fix. Two findings can target the
  // SAME field — a wrong scheme and a wrong path both live in `url` — and each
  // computes its new value from the current one. Computing both from the
  // original parse means the second write silently discards the first, which
  // looks like a successful repair that did not happen.
  let current = ctx.entry;

  for (const finding of findings) {
    const defect = ctx.contract.defect(finding.id);
    if (!defect.auto_fixable || !defect.fix_kind) continue;

    const permitted = repairPermitted(ctx.client, defect.fix_kind, ctx.os);
    if (!permitted.ok) {
      refused.push({ findingId: finding.id, reason: permitted.reason });
      continue;
    }

    const target = targetFor(finding, { ...ctx, entry: current });
    if (!target) {
      refused.push({
        findingId: finding.id,
        reason:
          finding.id === "config.auth-header-missing"
            ? `no key available — set ${ctx.contract.profile.credential.key_prefixes[0] ? "SUPERDOCS_API_KEY" : "the key variable"}`
            : "this repair could not be expressed as a single value change",
      });
      continue;
    }

    let edits: TextEdit[];
    if (ctx.format === "toml") {
      const tomlTarget = tomlTargetFor(target.path);
      const edit = tomlTarget ? tomlValueEdit(working, tomlTarget, String(target.value)) : null;
      if (!edit) {
        refused.push({
          findingId: finding.id,
          reason: "could not locate the value in the TOML source unambiguously",
        });
        continue;
      }
      edits = [edit];
    } else {
      edits = jsonEdits(working, target.path, target.value);
      if (edits.length === 0) {
        refused.push({ findingId: finding.id, reason: "the editor produced no change" });
        continue;
      }
    }

    // Verify each step against the text its offsets were computed from.
    // Checking the accumulated list at the end cannot work: every applied edit
    // shifts the offsets of the ones after it, so the assertion would be
    // comparing spans against bytes they no longer address.
    const step = applyOne(working, edits, ctx.format);
    if (!step.ok) {
      // Refuse the whole file rather than write a change we cannot vouch for.
      return {
        text,
        applied: [],
        refused,
        error: `refusing to write: ${finding.id} would have altered bytes outside its target (${step.reason})`,
      };
    }

    working = step.text;

    // Refresh the view of the entry so the next fix sees this one's result.
    const reparsed = parseByFormat(working, ctx.format);
    if (!reparsed.ok) {
      return {
        text,
        applied: [],
        refused,
        error: `refusing to write: ${finding.id} produced a file that no longer parses`,
      };
    }
    current = entryAt(reparsed.root.value, ctx.entryPath) ?? current;

    applied.push({
      findingId: finding.id,
      fixKind: defect.fix_kind,
      description: target.description,
      edits,
    });
  }

  return { text: working, applied, refused };
}

/**
 * Add a missing entry at an explicitly selected registry container.
 *
 * This deliberately lives outside `planFixes`: there is no existing entry to
 * supply as its context. The caller has already established that the document
 * has exactly one safe, non-wildcard destination; we never choose between
 * project blocks or create a server in an unknown shape.
 */
export function planAddEntry(
  findings: Finding[],
  ctx: AddEntryContext,
  text: string,
): FixOutcome {
  const applied: PlannedFix[] = [];
  const refused: { findingId: string; reason: string }[] = [];
  const missing = findings.find((f) => f.id === "config.no-entry");
  if (!missing) return { text, applied, refused };

  const defect = ctx.contract.defect(missing.id);
  const permitted = repairPermitted(ctx.client, defect.fix_kind ?? "add-entry", ctx.os);
  if (!permitted.ok) {
    refused.push({ findingId: missing.id, reason: permitted.reason });
    return { text, applied, refused };
  }
  if (!ctx.key || ctx.key.trim() === "") {
    refused.push({
      findingId: missing.id,
      reason: "no key available — set SUPERDOCS_API_KEY before adding an entry",
    });
    return { text, applied, refused };
  }

  const schema = ctx.client.http_server_schema;
  const headersField = schema.headers.field;
  if (!schema.headers.supported || !headersField) {
    refused.push({
      findingId: missing.id,
      reason: "this client has no verified request-header field for a SuperDocs key",
    });
    return { text, applied, refused };
  }

  const entry: Record<string, unknown> = {};
  if (schema.transport.field && schema.transport.preferred) {
    entry[schema.transport.field] = schema.transport.preferred;
  }
  entry[schema.url.field] = ctx.contract.profile.canonical.url;
  entry[headersField] = {
    [schema.headers.authorization_header ?? "Authorization"]:
      `${ctx.contract.profile.credential.header_scheme} ${ctx.key}`,
  };

  let edits: TextEdit[];
  if (ctx.format === "toml") {
    // TOML has no generic source-splice library. Appending complete tables is
    // unambiguous, leaves every existing byte untouched, and is only allowed
    // for the registry's simple known container (currently Codex).
    const table = [...ctx.containerPath, "superdocs"].join(".");
    const headerTable = [...ctx.containerPath, "superdocs", headersField].join(".");
    const transport = schema.transport.field && schema.transport.preferred
      ? `${schema.transport.field} = ${JSON.stringify(schema.transport.preferred)}\n`
      : "";
    const prefix = text.length === 0 || text.endsWith("\n") ? "\n" : "\n\n";
    const content =
      `${prefix}[${table}]\n` +
      transport +
      `${schema.url.field} = ${JSON.stringify(ctx.contract.profile.canonical.url)}\n\n` +
      `[${headerTable}]\n` +
      `${schema.headers.authorization_header ?? "Authorization"} = ` +
      `${JSON.stringify(`${ctx.contract.profile.credential.header_scheme} ${ctx.key}`)}\n`;
    edits = [{ offset: text.length, length: 0, content }];
  } else {
    edits = jsonEdits(text, [...ctx.containerPath, "superdocs"], entry);
  }
  if (edits.length === 0) {
    refused.push({ findingId: missing.id, reason: "the editor produced no change" });
    return { text, applied, refused };
  }

  const step = applyOne(text, edits, ctx.format);
  if (!step.ok) {
    return {
      text,
      applied: [],
      refused,
      error: `refusing to write: config.no-entry would have altered bytes outside its target (${step.reason})`,
    };
  }
  const parsed = parseByFormat(step.text, ctx.format);
  if (!parsed.ok) {
    return {
      text,
      applied: [],
      refused,
      error: "refusing to write: config.no-entry produced a file that no longer parses",
    };
  }
  applied.push({
    findingId: missing.id,
    fixKind: defect.fix_kind ?? "add-entry",
    description: "add a SuperDocs entry",
    edits,
  });
  return { text: step.text, applied, refused };
}

/**
 * Apply one fix and prove it touched nothing else.
 *
 * Kept separate from planFixes so the assertion runs per step, where the
 * offsets are still valid against the text they were computed from.
 */
export function applyOne(
  text: string,
  edits: TextEdit[],
  format: Format,
): { ok: true; text: string } | { ok: false; reason: string } {
  const after = format === "toml" ? applyTextEdits(text, edits) : applyJsonEdits(text, edits);
  const verdict = assertOnlySpansChanged(text, after, edits);
  if (!verdict.ok) return { ok: false, reason: verdict.reason };
  return { ok: true, text: after };
}
