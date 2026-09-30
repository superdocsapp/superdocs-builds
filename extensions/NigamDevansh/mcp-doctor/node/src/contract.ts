// Loads shared/ — the single source of truth both implementations read.
//
// Nothing here interprets the data; it only finds and types it. Every decision
// this tool makes is a lookup into these files, which is what keeps the
// TypeScript and Python behaviour comparable.
//
// FINDING THE RIGHT COPY MATTERS MORE THAN IT LOOKS. A published package
// carries its own copy of shared/, so in the repository there can be two: the
// real one and a bundled snapshot. Loading the snapshot would mean editing the
// contract and watching the tests pass against yesterday's data — the exact
// failure the shared contract exists to prevent. Two defences:
//
//   * the snapshot is only produced at `prepack`, never by `build`, so it does
//     not exist during development at all; and
//   * if one somehow does exist, the SOURCE tree is preferred, identified by
//     its sibling `tools/validate_contract.py` — a file the bundle never has.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type {
  ClientEntry,
  DefectCatalogue,
  Defect,
  EndpointProfile,
  PathBases,
} from "./types.js";

const here = dirname(fileURLToPath(import.meta.url));

const CANDIDATES = [
  join(here, "..", "..", "shared"), // node/(src|dist)/../../shared — the source tree
  join(here, "..", "shared"), // <pkg>/dist/../shared — the published bundle
  join(here, "..", "..", "..", "shared"),
];

function isContract(dir: string): boolean {
  return existsSync(join(dir, "defects.json")) && existsSync(join(dir, "clients"));
}

/** The source tree keeps the validator beside shared/; a bundle never does. */
function isSourceTree(dir: string): boolean {
  return existsSync(join(dir, "..", "tools", "validate_contract.py"));
}

export function findSharedRoot(
  candidates: string[] = CANDIDATES,
  env: NodeJS.ProcessEnv = process.env,
): string {
  // An explicit override, for tests and for a vendored contract. Safe only
  // because assertCanonical below re-checks the endpoint at load time — see
  // there for why pointing this at an arbitrary directory cannot redirect a key.
  const override = env.MCP_DOCTOR_SHARED;
  if (override) {
    if (!isContract(override)) throw new Error(`MCP_DOCTOR_SHARED is not a contract: ${override}`);
    return resolve(override);
  }
  const valid = candidates.filter(isContract).map((c) => resolve(c));
  const source = valid.find(isSourceTree);
  if (source) return source;
  if (valid.length > 0) return valid[0]!;
  throw new Error(
    `Could not locate the shared contract. Looked in:\n  ${candidates.join("\n  ")}`,
  );
}

/** The one address that may ever receive a user's key. */
const CANONICAL_URL = "https://api.superdocs.app/mcp";

/**
 * Re-check the endpoint at load time.
 *
 * validate_contract.py pins this, but that runs in CI against the repository —
 * it says nothing about the bytes actually loaded here. A vendored, edited or
 * substituted contract would otherwise decide where an authenticated request
 * goes. Two independent checks for the same property, because the consequence
 * of getting it wrong is exfiltrating a credential.
 */
export function assertCanonical(profile: EndpointProfile): void {
  const url = profile?.canonical?.url;
  if (url !== CANONICAL_URL) {
    throw new Error(
      `refusing to run: the loaded contract points at ${JSON.stringify(url)}, ` +
        `not ${CANONICAL_URL}`,
    );
  }
  const parsed = new URL(url);
  if (
    parsed.protocol !== "https:" ||
    parsed.username ||
    parsed.password ||
    parsed.port ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error(`refusing to run: the canonical URL is not a bare https origin`);
  }
  if (profile.canonical.follow_redirects !== false) {
    throw new Error(
      `refusing to run: the contract permits following redirects, which could carry ` +
        `the Authorization header to another origin`,
    );
  }
}

function readJson<T>(path: string): T {
  return JSON.parse(readFileSync(path, "utf8")) as T;
}

export interface Contract {
  root: string;
  profile: EndpointProfile;
  catalogue: DefectCatalogue;
  bases: PathBases;
  clients: ClientEntry[];
  defect(id: string): Defect;
}

let cached: Contract | undefined;

export function loadContract(root = findSharedRoot()): Contract {
  if (cached && cached.root === root) return cached;

  const catalogue = readJson<DefectCatalogue>(join(root, "defects.json"));
  const byId = new Map(catalogue.defects.map((d) => [d.id, d]));

  const clients = readdirSync(join(root, "clients"))
    .filter((f) => f.endsWith(".json"))
    .map((f) => readJson<ClientEntry>(join(root, "clients", f)))
    .sort((a, b) => a.id.localeCompare(b.id)); // deterministic ordering

  const profile = readJson<EndpointProfile>(join(root, "profile", "superdocs.json"));
  assertCanonical(profile);

  cached = {
    root,
    profile,
    catalogue,
    bases: readJson<PathBases>(join(root, "path-bases.json")),
    clients,
    defect(id: string): Defect {
      const d = byId.get(id);
      // A missing id means the code emits something the contract does not
      // define — which the conformance suite could never reconcile.
      if (!d) throw new Error(`defect '${id}' is not in the shared catalogue`);
      return d;
    },
  };
  return cached;
}
