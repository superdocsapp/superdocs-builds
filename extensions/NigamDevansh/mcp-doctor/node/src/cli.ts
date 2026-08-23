#!/usr/bin/env node
// The command line. --fix writes only what the client registry sanctions; every
// other mode is read-only.

import { realpathSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadContract } from "./contract.js";
import { renderJson, renderRepair, renderReport, renderText } from "./render.js";
import { repair } from "./repair.js";
import { defaultOptions, scan, VERSION } from "./scan.js";

const USAGE = `mcp-doctor ${VERSION} — diagnose SuperDocs MCP client configuration

  mcp-doctor                  scan every supported client
  mcp-doctor --client <id>    restrict to one client
  mcp-doctor --config <path>  diagnose one specific file
  mcp-doctor --key-env <name> credential source (default SUPERDOCS_API_KEY)
  mcp-doctor --fix            back up, repair what is sanctioned, re-check
  mcp-doctor --report         redacted Markdown for a support thread
  mcp-doctor --json           machine-readable findings
  mcp-doctor --version        print the version

Exit codes: 0 clean, 1 manual action remains, 2 tool or usage error.

--fix repairs only what the client registry sanctions. A client is write-capable
only once its configuration knowledge is captured from a real installation.
`;
function realpathOrSelf(path: string): string {
  try {
    return realpathSync(path);
  } catch {
    return path;
  }
}

interface Args {
  client?: string;
  keyEnv?: string;
  config?: string;
  json: boolean;
  report: boolean;
  help: boolean;
  version: boolean;
  fix: boolean;
  error?: string;
}

// Flags that consume the next argument.
const VALUED = new Set(["--client", "--config", "--key-env"]);

export function parseArgs(argv: string[]): Args {
  const args: Args = { json: false, report: false, help: false, version: false, fix: false };

  const assign = (flag: string, value: string | undefined): boolean => {
    // A missing value used to fall through as `undefined` and silently run a
    // full scan exiting 0 — the user asked a narrow question and got a broad,
    // confident answer to a different one.
    if (value === undefined || value.startsWith("-")) {
      args.error = `${flag} requires a value`;
      return false;
    }
    if (flag === "--client") args.client = value;
    else if (flag === "--config") args.config = value;
    else if (flag === "--key-env") args.keyEnv = value;
    return true;
  };

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--json") args.json = true;
    else if (a === "--report") args.report = true;
    else if (a === "--fix") args.fix = true;
    else if (a === "-h" || a === "--help") args.help = true;
    else if (a === "-V" || a === "--version") args.version = true;
    else if (VALUED.has(a)) {
      if (!assign(a, argv[++i])) return args;
    } else if (a.includes("=") && VALUED.has(a.slice(0, a.indexOf("=")))) {
      const flag = a.slice(0, a.indexOf("="));
      if (!assign(flag, a.slice(a.indexOf("=") + 1))) return args;
    } else {
      args.error = `unknown argument: ${a}`;
      return args;
    }
  }
  return args;
}

export function run(
  argv: string[],
  env: NodeJS.ProcessEnv = process.env,
  cwd: string = process.cwd(),
): { stdout: string; stderr: string; code: number } {
  const args = parseArgs(argv);

  if (args.help) return { stdout: USAGE, stderr: "", code: 0 };
  if (args.version) return { stdout: `${VERSION}\n`, stderr: "", code: 0 };
  if (args.error) return { stdout: "", stderr: `${args.error}\n\n${USAGE}`, code: 2 };

  const contract = loadContract();
  const opts = defaultOptions(env);
  opts.cwd = realpathOrSelf(cwd);
  if (args.client) opts.clientFilter = args.client;
  if (args.keyEnv) opts.keyEnvVar = args.keyEnv;
  if (args.config) opts.singleFile = realpathOrSelf(resolve(cwd, args.config));

  if (args.client && !contract.clients.some((c) => c.id === args.client)) {
    const known = contract.clients.map((c) => c.id).join(", ");
    return { stdout: "", stderr: `unknown client '${args.client}'. Known: ${known}\n`, code: 2 };
  }
  if (args.config && args.client === undefined && opts.singleFile) {
    // A file alone does not say which client's schema to read it against.
    const guess = contract.clients.filter((c) =>
      c.locations.some((l) => opts.singleFile!.endsWith(l.path.split("/").pop()!)),
    );
    if (guess.length === 1) opts.clientFilter = guess[0]!.id;
    else if (guess.length === 0) {
      return {
        stdout: "",
        stderr:
          `cannot tell which client '${args.config}' belongs to.\n` +
          `Pass --client as well: ${contract.clients.map((c) => c.id).join(", ")}\n`,
        code: 2,
      };
    }
  }

  if (args.fix) {
    // Passing --fix IS the consent (D2): no prompt, no --yes. The backup is
    // the recovery path, and every write is gated by the registry.
    const result = repair(contract, opts);
    const stdout = args.json
      ? JSON.stringify(result.after, null, 2) + "\n"
      : renderRepair(result) + "\n";
    return { stdout, stderr: "", code: result.exitCode };
  }

  const report = scan(contract, opts);

  // An explicitly named client that has nothing configured is a direct question
  // deserving a direct answer, so it exits 1 rather than the informational 0.
  if (args.client) {
    const target = report.clients.find((c) => c.id === args.client);
    const present = target?.config_files.some((f) => f.status !== "absent") ?? false;
    const hasEntry = target?.config_files.some((f) => (f.entries?.length ?? 0) > 0) ?? false;
    if (!present || !hasEntry) report.exit_code = 1;
  }

  const stdout = args.json
    ? renderJson(report) + "\n"
    : args.report
      ? renderReport(report)
      : renderText(report, Boolean(env.FORCE_COLOR) || (process.stdout.isTTY ?? false)) + "\n";

  return { stdout, stderr: "", code: report.exit_code };
}

/** True when this module was started directly, rather than imported.
 *
 *  Comparing basenames split on "/" breaks on Windows, where argv[1] is
 *  backslash-separated. Resolving both sides to a real path compares what the
 *  OS actually thinks they are. */
export function isDirectRun(moduleUrl: string, argv1: string | undefined): boolean {
  if (!argv1) return false;
  const real = (p: string): string => {
    try {
      return realpathSync(p);
    } catch {
      return resolve(p);
    }
  };
  try {
    return real(fileURLToPath(moduleUrl)) === real(argv1);
  } catch {
    return false;
  }
}

if (isDirectRun(import.meta.url, process.argv[1]) || process.env.MCP_DOCTOR_FORCE_MAIN === "1") {
  const { stdout, stderr, code } = run(process.argv.slice(2));
  if (stdout) process.stdout.write(stdout);
  if (stderr) process.stderr.write(stderr);
  process.exit(code);
}
