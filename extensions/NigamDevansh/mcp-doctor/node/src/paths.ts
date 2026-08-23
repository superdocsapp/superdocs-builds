// Resolving a location to a real path, using ONLY what path-bases.json says.
//
// The temptation here is to reach for os.homedir() and be done. That is exactly
// how two implementations end up disagreeing about which file they are reading:
// one honours $HOME, the other honours the OS API, and on a machine where they
// differ the two tools give different answers to the same question. So the rule
// comes from data, and this module is just the lookup.

import { existsSync } from "node:fs";
import { dirname, isAbsolute, join, parse, resolve } from "node:path";
import type { Location, OsName, PathBases } from "./types.js";

export interface Resolved {
  path: string | null;
  /** Why it could not be resolved — reported, never guessed around. */
  unresolvable?: string;
}

export function currentOs(platform: string = process.platform): OsName | null {
  if (platform === "darwin" || platform === "linux" || platform === "win32") return platform;
  return null;
}

/** Expand a `$VAR`-style fallback using the supplied environment. */
function expandFallback(fallback: string, env: NodeJS.ProcessEnv): string | null {
  if (fallback === "~") return env.HOME ?? null;
  return fallback.replace(/\$([A-Z_][A-Z0-9_]*)/g, (whole, name: string) => env[name] ?? whole);
}

function findProjectRoot(
  start: string,
  markers: string[],
  ascend: boolean,
  env: NodeJS.ProcessEnv,
): string {
  if (!ascend) return start;
  // The SUPPLIED environment, never process.env: a fixture declares its inputs,
  // and reading the ambient machine would let the same declared inputs pick
  // different roots here and in the Python implementation.
  const homeVar = env.HOME ?? env.USERPROFILE;
  const home = homeVar ? resolve(homeVar) : null;
  let dir = resolve(start);
  const { root } = parse(dir);
  while (true) {
    if (markers.some((m) => existsSync(join(dir, m)))) return dir;
    if (dir === root) break;
    // Stop at the home directory: a marker above it belongs to someone else's
    // project, not this one.
    if (home && dir === home) break;
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return resolve(start);
}

export interface ResolveOptions {
  os: OsName;
  cwd: string;
  env: NodeJS.ProcessEnv;
}

export function resolveBase(
  baseName: string,
  bases: PathBases,
  opts: ResolveOptions,
): Resolved {
  const base = bases.bases[baseName];
  if (!base) return { path: null, unresolvable: `base '${baseName}' is not defined` };

  if (baseName === "project_root") {
    const markers = base.markers ?? [];
    return { path: findProjectRoot(opts.cwd, markers, base.ascend ?? false, opts.env) };
  }

  const rule = base[opts.os];
  if (!rule) return { path: null, unresolvable: `base '${baseName}' has no rule for ${opts.os}` };

  for (const name of rule.from_env) {
    const value = opts.env[name];
    if (value && value.trim() !== "") return { path: value };
  }

  if (rule.fallback === null) {
    return {
      path: null,
      unresolvable:
        `base '${baseName}' needs one of ${rule.from_env.join(", ") || "(no variables)"} ` +
        `on ${opts.os}, and none is set`,
    };
  }

  const expanded = expandFallback(rule.fallback, opts.env);
  if (!expanded || expanded.includes("$")) {
    return { path: null, unresolvable: `base '${baseName}' fallback could not be expanded` };
  }
  return { path: expanded };
}

/** Full path for a location, or why there isn't one. */
export function resolveLocation(
  location: Location,
  bases: PathBases,
  opts: ResolveOptions,
): Resolved {
  if (!location.os.includes(opts.os)) {
    return { path: null, unresolvable: `not configured for ${opts.os}` };
  }
  const base = resolveBase(location.base, bases, opts);
  if (!base.path) return base;

  // Stored paths are always '/'-separated portable segments (path-bases.json
  // rules.path_separator_in_data), so split and re-join for the host platform.
  const segments = location.path.split("/").filter(Boolean);
  const full = join(base.path, ...segments);
  return { path: isAbsolute(full) ? full : resolve(opts.cwd, full) };
}
