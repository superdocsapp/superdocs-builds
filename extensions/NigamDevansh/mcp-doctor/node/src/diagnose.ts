// The diagnosis rules.
//
// ORDER IS THE DESIGN. Three short-circuits decide what is even asked:
//
//   1. stdio        — a local process; none of the remote checks apply.
//   2. host rule    — off the canonical host we have NO opinion, so every URL,
//                     header and credential check is skipped. Rewriting or even
//                     commenting on someone's gateway is not our business.
//   3. no headers   — a client that cannot send Authorization cannot hold a
//                     SuperDocs key, so "you forgot the header" would be the
//                     wrong finding entirely.
//
// Everything else is a lookup into shared/: field names, container keys,
// severities and message templates all come from data.

import type {
  ClientEntry,
  Defect,
  EndpointProfile,
  Finding,
  EntrySummary,
} from "./types.js";
import type { Contract as LoadedContract } from "./contract.js";
import type { ParsedNode } from "./parsers.js";

export interface EntryContext {
  name: string;
  raw: Record<string, unknown>;
  node?: ParsedNode;
  jsonPath: string;
}

export interface DiagnoseInput {
  contract: LoadedContract;
  client: ClientEntry;
  filePath: string;
  entries: EntryContext[];
  env: NodeJS.ProcessEnv;
  keyEnvVar: string;
}

/** Render a catalogue template. Only `data` values are substituted, and the
 *  contract's placeholder policy has already banned the dangerous names. */
export function render(template: string, data: Record<string, unknown>): string {
  return template.replace(/\{([a-z_][a-z0-9_]*)\}/g, (whole, name: string) =>
    name in data ? String(data[name]) : whole,
  );
}

export function finding(
  defect: Defect,
  data: Record<string, unknown>,
  extra: Partial<Finding> = {},
): Finding {
  return {
    id: defect.id,
    class: defect.class,
    severity: defect.severity,
    message: render(defect.message, data),
    remediation: defect.remediation ? render(defect.remediation, data) : null,
    auto_fixable: defect.auto_fixable,
    ...extra,
    data: data as Finding["data"],
  };
}

function hostOf(url: string): string | null {
  try {
    // The WHATWG parser strips userinfo from `host`, which is what we want:
    // https://secret@gw.example/mcp yields "gw.example" and the credential is
    // never carried into a message.
    return new URL(url).host.toLowerCase();
  } catch {
    return null;
  }
}

function isCanonicalHost(host: string | null, profile: EndpointProfile): boolean {
  // EXACT comparison. A suffix check would accept api.superdocs.app.evil.example
  // and send a live key to it.
  return host !== null && host === profile.canonical.host.toLowerCase();
}

function headerValue(
  entry: Record<string, unknown>,
  client: ClientEntry,
  wanted: string,
): { present: boolean; value?: string } {
  const field = client.http_server_schema.headers.field;
  if (!field) return { present: false };
  const headers = entry[field];
  if (typeof headers !== "object" || headers === null) return { present: false };
  const target = wanted.toLowerCase();
  for (const [k, v] of Object.entries(headers as Record<string, unknown>)) {
    if (k.toLowerCase() === target) return { present: true, value: String(v) };
  }
  return { present: false };
}

function isStdio(entry: Record<string, unknown>, client: ClientEntry): boolean {
  const markers = client.http_server_schema.transport.stdio_indicator_fields ?? [];
  return markers.some((f) => f in entry);
}

export function diagnoseEntry(input: DiagnoseInput, entry: EntryContext): Finding[] {
  const { contract, client, filePath } = input;
  const { profile } = contract;
  const schema = client.http_server_schema;
  const out: Finding[] = [];
  const base = { client: client.name, path: filePath };
  const loc = { path: filePath, json_path: entry.jsonPath };

  // ① stdio — a local process, out of scope.
  if (isStdio(entry.raw, client)) {
    out.push(
      finding(contract.defect("scope.stdio-server"), base, { client: client.name, location: loc }),
    );
    return out;
  }

  const urlField = schema.url.field;
  const rawUrl = entry.raw[urlField];

  if (typeof rawUrl !== "string" || rawUrl === "") {
    out.push(finding(contract.defect("config.url-missing"), base, { client: client.name, location: loc }));
    return out;
  }

  const host = hostOf(rawUrl);

  // ② THE HOST RULE — everything below is skipped off the canonical host.
  if (!isCanonicalHost(host, profile)) {
    out.push(
      finding(
        contract.defect("scope.non-canonical-host"),
        { ...base, host: host ?? "(unparseable)", canonical_host: profile.canonical.host },
        { client: client.name, location: loc },
      ),
    );
    return out;
  }

  // ③ A client with no header mechanism cannot hold a SuperDocs key.
  if (!schema.headers.supported) {
    out.push(
      finding(
        contract.defect("scope.client-cannot-authenticate"),
        { ...base, reason: schema.headers.unsupported_reason ?? "no headers field" },
        { client: client.name, location: loc },
      ),
    );
    return out;
  }

  // ── On the canonical host, with a client that can authenticate ──
  const parsed = new URL(rawUrl);

  if (parsed.username || parsed.password) {
    out.push(
      finding(contract.defect("config.url-embedded-credentials"), base, {
        client: client.name,
        location: loc,
      }),
    );
  }

  if (parsed.protocol !== `${profile.canonical.scheme}:`) {
    out.push(
      finding(contract.defect("config.scheme-insecure"), base, {
        client: client.name,
        location: loc,
      }),
    );
  }

  const aliases = profile.canonical.path_aliases ?? [profile.canonical.path];
  if (!aliases.includes(parsed.pathname)) {
    out.push(
      finding(
        contract.defect("config.path-wrong"),
        { ...base, found: parsed.pathname, expected: profile.canonical.path },
        { client: client.name, location: loc },
      ),
    );
  }
  // WHATWG URL normalises a bare trailing `?` / `#` to empty search/hash;
  // the pinned endpoint forbids even those delimiters, so retain the raw
  // source check as well as the parsed components.
  if (parsed.search || parsed.hash || rawUrl.includes("?") || rawUrl.includes("#")) {
    out.push(
      finding(contract.defect("config.url-query-or-fragment"), base, {
        client: client.name,
        location: loc,
      }),
    );
  }

  // Transport shape, when the client names it explicitly.
  const transport = schema.transport;
  if (transport.detected_by === "type-field" && transport.field) {
    const found = entry.raw[transport.field];
    if (found !== undefined && !transport.http_values.includes(String(found))) {
      out.push(
        finding(
          contract.defect("config.transport-not-http"),
          { ...base, found: String(found), expected: transport.preferred ?? "http" },
          { client: client.name, location: loc },
        ),
      );
    }
  }

  // Authorization.
  const authHeader = schema.headers.authorization_header ?? "Authorization";
  const auth = headerValue(entry.raw, client, authHeader);
  const scheme = profile.credential.header_scheme;

  if (!auth.present) {
    out.push(
      finding(contract.defect("config.auth-header-missing"), base, {
        client: client.name,
        location: loc,
      }),
    );
  } else {
    const value = (auth.value ?? "").trim();
    const doubled = new RegExp(`^${scheme}\\s+${scheme}\\s+`, "i");
    if (doubled.test(value)) {
      out.push(
        finding(contract.defect("config.auth-header-doubled-bearer"), base, {
          client: client.name,
          location: loc,
        }),
      );
    } else if (!new RegExp(`^${scheme}\\s+`, "i").test(value)) {
      out.push(
        finding(contract.defect("config.auth-header-no-bearer"), base, {
          client: client.name,
          location: loc,
        }),
      );
    } else {
      const token = value.slice(scheme.length).trim();
      const placeholder = /^\$\{?([A-Za-z_][A-Za-z0-9_]*)(:-[^}]*)?\}?$|^\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}$/.exec(
        token,
      );
      if (placeholder) {
        const variable = placeholder[1] ?? placeholder[3] ?? "";
        const fallback = placeholder[2]?.slice(2);
        const resolved = input.env[variable]?.trim() || fallback;
        if (!resolved || resolved.trim() === "") {
          out.push(
            finding(
              contract.defect("config.env-placeholder-unresolved"),
              { ...base, variable },
              { client: client.name, location: loc },
            ),
          );
        }
      } else if (!profile.credential.key_prefixes.some((p) => token.startsWith(p))) {
        out.push(
          finding(
            contract.defect("config.key-shape-unexpected"),
            { ...base, expected_prefixes: profile.credential.key_prefixes.join(" or ") },
            { client: client.name, location: loc },
          ),
        );
      }
    }
  }

  // An Accept override the server would answer with 406.
  const acceptName = schema.headers.accept_header ?? "Accept";
  const accept = headerValue(entry.raw, client, acceptName);
  if (accept.present) {
    const value = accept.value ?? "";
    const required = profile.accept_header.must_include;
    // A wildcard is NOT sufficient — measured, see the endpoint profile.
    if (!value.toLowerCase().includes(required.toLowerCase())) {
      out.push(
        finding(
          contract.defect("config.accept-header-incompatible"),
          { ...base, found: value },
          { client: client.name, location: loc },
        ),
      );
    }
  }

  return out;
}

export function summariseEntry(
  entry: EntryContext,
  client: ClientEntry,
  profile: EndpointProfile,
): EntrySummary {
  if (isStdio(entry.raw, client)) {
    return { name: entry.name, kind: "stdio", in_scope: false };
  }
  const url = entry.raw[client.http_server_schema.url.field];
  if (typeof url !== "string") return { name: entry.name, kind: "unknown", in_scope: false };
  const host = hostOf(url);
  const canonical = isCanonicalHost(host, profile);
  // Host only. Never the URL — it can carry a credential in its userinfo.
  return {
    name: entry.name,
    kind: "http",
    host: host ?? undefined,
    canonical,
    in_scope: canonical,
  };
}

export { hostOf, isCanonicalHost, isStdio };
export type { ClientEntry, EndpointProfile };
