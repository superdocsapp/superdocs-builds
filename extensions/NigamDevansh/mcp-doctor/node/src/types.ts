// Shapes mirroring shared/schema/*. Kept hand-written rather than generated so
// the compiler complains in this package when the contract changes, instead of a
// generator silently absorbing it.

export type Severity = "error" | "warn" | "info";
export type DefectClass = "ok" | "config" | "scope" | "network" | "auth" | "drift";
export type OsName = "darwin" | "linux" | "win32";
export type Format = "json" | "jsonc" | "toml";
export type EvidenceTier = "captured" | "documented" | "unverified";

export interface Defect {
  id: string;
  class: DefectClass;
  severity: Severity;
  title: string;
  message: string;
  remediation: string | null;
  auto_fixable: boolean;
  fix_kind?: string;
}

export interface DefectCatalogue {
  catalogue_version: number;
  placeholder_policy: { forbidden: string[] };
  defects: Defect[];
}

export interface Claim {
  status: EvidenceTier;
  date?: string;
  how?: string;
}

export interface Location {
  scope: "project" | "workspace" | "user";
  precedence: number;
  format: Format;
  os: OsName[];
  base: string;
  path: string;
  note?: string;
  containers?: { json_path: string; scope_hint?: string }[];
}

export interface ClientEntry {
  id: string;
  name: string;
  entry_version: number;
  evidence: {
    paths: Record<OsName, Claim>;
    schema: Claim;
    repairs: Claim;
  };
  write_capable: Record<OsName, boolean>;
  locations: Location[];
  server_map: { container_key: string; shape: "object" | "array" };
  http_server_schema: {
    transport: {
      detected_by: "type-field" | "url-field-presence";
      field: string | null;
      http_values: string[];
      preferred: string | null;
      stdio_indicator_fields?: string[];
      sse_only?: boolean;
    };
    url: { field: string };
    headers: {
      supported: boolean;
      field?: string;
      authorization_header?: string;
      accept_header?: string;
      client_sends_own_accept?: boolean;
      unsupported_reason?: string;
    };
    env_interpolation?: { supported: boolean; syntax?: string; with_default?: string };
  };
  identification: {
    // `flags` is separate from `matches` on purpose: an inline (?i) group is
    // Python-only and throws in JavaScript.
    rules: { by: "url_host" | "name"; equals?: string; matches?: string; flags?: string }[];
  };
  repairs: { allowed: string[]; planned?: string[] };
}

export interface EndpointProfile {
  canonical: {
    url: string;
    host: string;
    path: string;
    scheme: string;
    follow_redirects: boolean;
    path_aliases?: string[];
  };
  credential: { key_prefixes: string[]; header_name: string; header_scheme: string };
  accept_header: { must_include: string };
  inventory: { tools: number; prompts: number; resources: number };
}

export interface PathBases {
  bases: Record<
    string,
    Record<OsName, { from_env: string[]; fallback: string | null }> & {
      markers?: string[];
      ascend?: boolean;
    }
  >;
}

// ── Findings: the --json wire contract (shared/schema/findings.schema.json) ──

export interface Finding {
  id: string;
  class: DefectClass;
  severity: Severity;
  message: string;
  remediation?: string | null;
  client?: string | null;
  location?: { path?: string; json_path?: string; line?: number; column?: number };
  auto_fixable?: boolean;
  fixed?: boolean;
  data?: Record<string, string | number | boolean | null>;
}

export interface EntrySummary {
  name: string;
  kind: "http" | "stdio" | "unknown";
  host?: string;
  canonical?: boolean;
  in_scope?: boolean;
}

export interface ConfigFileReport {
  path: string;
  scope: "project" | "workspace" | "user";
  format: Format;
  status: "ok" | "absent" | "unreadable" | "invalid";
  entries?: EntrySummary[];
}

export interface ClientReport {
  id: string;
  name: string;
  write_capable: boolean;
  evidence_tier: EvidenceTier;
  config_files: ConfigFileReport[];
}

export interface Report {
  schema_version: number;
  tool: { name: "mcp-doctor"; version: string; implementation: "typescript" | "python" };
  generated_at?: string;
  duration_ms?: number;
  summary: {
    clients_scanned: number;
    config_files_read: number;
    entries_found: number;
    errors: number;
    warnings: number;
    fixed: number;
    connection?: "connected" | "connected-with-drift" | "failed" | "not-attempted";
  };
  clients: ClientReport[];
  findings: Finding[];
  connection?: null;
  exit_code: 0 | 1 | 2;
}
