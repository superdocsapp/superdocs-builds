/**
 * Headless manuscript compiler.
 *
 * The plugin and this CLI share the same core; only the vault adapter and the
 * transport differ. That is not an accident of layering — it is what makes the
 * compiler testable, CI-runnable, and usable by people who keep their book in a
 * git repository rather than in Obsidian.
 *
 *   manuscript compile <vault> [--spine Manuscript.md] [--out build]
 *                              [--format pdf,docx,html] [--offline] [--strict]
 *                              [--clean] [--json]
 *   manuscript check <vault>       compile and report diagnostics, write nothing
 *   manuscript scale [--chapters 60] [--keep]
 *                                  build a book-sized vault on disk and prove the
 *                                  300-page claims against it: correct continuous
 *                                  numbering, a byte-identical recompile, and a
 *                                  one-chapter edit that re-renders one chapter
 *   manuscript status              show the SuperDocs account's remaining operations
 *   manuscript roundtrip <vault>   drive all four SuperDocs calls end to end:
 *                                  upload, chat in review mode, approve item by item,
 *                                  export. The approval decision is explicit
 *                                  (--decision approve-all | reject-all | approve-first),
 *                                  so a program makes the same call a human would.
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { compile } from "../core/compile";
import { summariseChanges } from "../core/cache";
import { DEFAULT_COMPILE_OPTIONS, type CompileOptions, type Diagnostic } from "../core/types";
import { FsVault } from "../vault/fs-vault";
import { SuperDocsClient, SuperDocsError, type ExportWarning } from "../superdocs/client";
import { nodeTransport } from "../superdocs/node-transport";
import { uploadFigures } from "../superdocs/figures";
import { renderStandaloneHtml } from "../core/standalone";
import { isSuperDocsError, roundtrip } from "./roundtrip";
import { runScale } from "./scale";

const CACHE_DIR = ".manuscript-cache";
const MANIFEST_FILE = "manifest.json";

interface Args {
  command: string;
  vault: string;
  spine: string;
  out: string;
  formats: string[];
  offline: boolean;
  strict: boolean;
  clean: boolean;
  json: boolean;
  paper: "Letter" | "A4" | "A3" | "Legal";
  /** roundtrip: what to do at the human gate. There is no default "yes". */
  decision: "approve-all" | "reject-all" | "approve-first";
  instruction: string;
}

function parseArgs(argv: string[]): Args {
  const positional: string[] = [];
  const flags = new Map<string, string>();
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i]!;
    if (a.startsWith("--")) {
      const eq = a.indexOf("=");
      if (eq > 0) flags.set(a.slice(2, eq), a.slice(eq + 1));
      else if (argv[i + 1] && !argv[i + 1]!.startsWith("--")) flags.set(a.slice(2), argv[++i]!);
      else flags.set(a.slice(2), "true");
    } else {
      positional.push(a);
    }
  }
  const paper = (flags.get("paper") ?? "A4") as Args["paper"];
  return {
    command: positional[0] ?? "compile",
    vault: positional[1] ?? ".",
    spine: flags.get("spine") ?? DEFAULT_COMPILE_OPTIONS.spinePath,
    out: flags.get("out") ?? "build",
    formats: (flags.get("format") ?? "html").split(",").map((f) => f.trim()).filter(Boolean),
    offline: flags.get("offline") === "true",
    strict: flags.get("strict") === "true",
    clean: flags.get("clean") === "true",
    json: flags.get("json") === "true",
    paper,
    decision: (flags.get("decision") ?? "approve-first") as Args["decision"],
    instruction:
      flags.get("instruction") ??
      "Add a short editor's note at the very top of the document, under the heading " +
        "'Editor's Note', saying that this proof was generated automatically. Change nothing else.",
  };
}

const RESET = "\u001b[0m";
const colour = (code: string, s: string): string =>
  process.stdout.isTTY ? `\u001b[${code}m${s}${RESET}` : s;
const red = (s: string) => colour("31", s);
const yellow = (s: string) => colour("33", s);
const grey = (s: string) => colour("90", s);
const green = (s: string) => colour("32", s);
const bold = (s: string) => colour("1", s);

function printDiagnostics(diags: Diagnostic[]): void {
  if (diags.length === 0) {
    console.log(green("No findings. Every citation, figure and cross-reference resolved."));
    return;
  }
  const order = { error: 0, warning: 1, info: 2 } as const;
  const sorted = [...diags].sort((a, b) => order[a.severity] - order[b.severity]);
  for (const d of sorted) {
    const tag =
      d.severity === "error" ? red("error") : d.severity === "warning" ? yellow("warn ") : grey("info ");
    const where = d.file ? grey(` ${d.file}${d.line ? `:${d.line}` : ""}`) : "";
    console.log(`  ${tag} ${grey(d.code)}${where}\n        ${d.message}`);
    if (d.snippet) console.log(grey(`        > ${d.snippet}`));
  }
}

async function main(): Promise<number> {
  const args = parseArgs(process.argv.slice(2));

  if (args.command === "status") return status();
  if (args.command === "roundtrip") return runRoundtrip(args);
  if (args.command === "scale") return runScale(process.argv.slice(3));
  if (args.command !== "compile" && args.command !== "check") {
    console.error(`Unknown command "${args.command}". Try: compile, check, scale, roundtrip, status.`);
    return 2;
  }

  const vaultRoot = resolve(args.vault);
  if (!existsSync(vaultRoot)) {
    console.error(red(`Vault not found: ${vaultRoot}`));
    return 2;
  }

  const options: CompileOptions = {
    ...DEFAULT_COMPILE_OPTIONS,
    spinePath: args.spine,
    strict: args.strict,
  };

  const vault = new FsVault(vaultRoot);
  const manifestPath = join(vaultRoot, CACHE_DIR, MANIFEST_FILE);
  const manifestJson =
    args.clean || !existsSync(manifestPath) ? null : await readFile(manifestPath, "utf-8");

  const t0 = performance.now();
  let result;
  try {
    result = await compile({
      vault,
      options,
      manifestJson,
      onProgress: (stage, detail) => {
        if (!args.json && process.stdout.isTTY) {
          process.stdout.write(`\r${grey(`${stage.padEnd(9)} ${(detail ?? "").slice(0, 60)}`)}\u001b[K`);
        }
      },
    });
  } catch (err) {
    if (!args.json && process.stdout.isTTY) process.stdout.write("\r\u001b[K");
    console.error(red(err instanceof Error ? err.message : String(err)));
    return 1;
  }
  if (!args.json && process.stdout.isTTY) process.stdout.write("\r\u001b[K");

  const counts = summariseChanges(result.changes);
  const wallMs = performance.now() - t0;

  if (args.json) {
    console.log(
      JSON.stringify(
        {
          ok: result.ok,
          stats: result.stats,
          changes: counts,
          reRendered: result.reRendered,
          timings: result.timings,
          diagnostics: result.diagnostics,
          wallMs,
        },
        null,
        2,
      ),
    );
  } else {
    console.log(bold(`\n${result.meta.title}`));
    if (result.meta.author) console.log(grey(result.meta.author));
    console.log(
      `\n${result.stats.chapters} chapters · ${result.stats.words.toLocaleString()} words · ` +
        `~${result.stats.estimatedPages} pages · ${result.stats.figures} figures · ` +
        `${result.stats.footnotes} footnotes · ${result.stats.citations} citations`,
    );
    console.log(
      grey(
        `incremental: ${counts.unchanged} unchanged, ${counts.renumbered} renumbered, ` +
          `${counts.rewritten} re-rendered, ${counts.added} added, ${counts.removed} removed`,
      ),
    );
    console.log(
      grey(
        `stages: ${result.timings
          .map((t) => `${t.stage} ${t.ms.toFixed(0)}ms`)
          .join(" · ")} · total ${wallMs.toFixed(0)}ms`,
      ),
    );
    console.log("");
    printDiagnostics(result.diagnostics);
  }

  if (args.command === "check") return result.ok ? 0 : 1;

  // --- write outputs --------------------------------------------------------
  const outDir = resolve(vaultRoot, args.out);
  await mkdir(outDir, { recursive: true });
  await mkdir(dirname(manifestPath), { recursive: true });

  const baseName = slugFilename(result.meta.title);
  let html = result.html;

  const wantsRemote = args.formats.some((f) => f === "pdf" || f === "docx");
  const apiKey = process.env.SUPERDOCS_API_KEY ?? (await readEnvFile(vaultRoot));

  if (wantsRemote && !args.offline) {
    if (!apiKey) {
      console.error(
        red(
          "\nPDF and DOCX export needs a SuperDocs API key. Set SUPERDOCS_API_KEY, or pass --offline to write HTML only.",
        ),
      );
      return 1;
    }
    const client = new SuperDocsClient({ apiKey, transport: nodeTransport });

    // Figures must become hosted URLs before export: data: URIs and local paths
    // are dropped from the .docx and PDF without any warning.
    const uploaded = await uploadFigures({
      html,
      figures: result.assignedFigures,
      vault,
      client,
      cache: result.manifest.imageUrls,
      onProgress: (done, total) =>
        process.stdout.isTTY &&
        process.stdout.write(`\r${grey(`uploading figures ${done}/${total}`)}\u001b[K`),
    });
    if (process.stdout.isTTY) process.stdout.write("\r\u001b[K");
    html = uploaded.html;
    for (const d of uploaded.diagnostics) result.diagnostics.push(d);
    if (uploaded.diagnostics.length) printDiagnostics(uploaded.diagnostics);

    for (const format of args.formats) {
      if (format === "html") continue;
      if (format !== "pdf" && format !== "docx" && format !== "markdown" && format !== "txt") {
        console.error(yellow(`Skipping unknown format "${format}".`));
        continue;
      }
      try {
        const exported = await client.exportDocument({
          format,
          html,
          options: { paper_size: args.paper, margins: "normal", filename: baseName },
        });
        const target = join(outDir, `${baseName}.${format === "markdown" ? "md" : format}`);
        await writeFile(target, Buffer.from(exported.bytes));
        reportExport(target, exported.bytes.byteLength, exported.warnings);
      } catch (err) {
        const message =
          err instanceof SuperDocsError ? `${err.message} (${err.status})` : String(err);
        console.error(red(`  ${format} export failed: ${message}`));
        return 1;
      }
    }
  } else if (wantsRemote && args.offline) {
    console.log(yellow("\n--offline: skipped PDF and DOCX (both are rendered by SuperDocs)."));
  }

  if (args.formats.includes("html") || args.offline || args.formats.length === 0) {
    const target = join(outDir, `${baseName}.html`);
    await writeFile(target, renderStandaloneHtml(result.html, result.meta), "utf-8");
    console.log(green(`  wrote ${target} (${(result.html.length / 1024).toFixed(0)} KB)`));
  }

  await writeFile(manifestPath, JSON.stringify(result.manifest), "utf-8");

  return result.ok ? 0 : 1;
}

function reportExport(path: string, bytes: number, warnings: ExportWarning[]): void {
  console.log(green(`  wrote ${path} (${(bytes / 1024).toFixed(0)} KB)`));
  for (const w of warnings) {
    console.log(yellow(`    export warning ${w.code}: ${w.message}`));
  }
}

/**
 * Drive the whole contract from a program: upload, chat, approve, export.
 *
 * The gate is part of the flow rather than a UI step — `--decision` is the caller
 * making the call, explicitly, the same way a person would in the review modal.
 */
async function runRoundtrip(args: Args): Promise<number> {
  const vaultRoot = resolve(args.vault);
  const apiKey = process.env.SUPERDOCS_API_KEY ?? (await readEnvFile(vaultRoot));
  if (!apiKey) {
    console.error(red("The round trip needs a live key. Set SUPERDOCS_API_KEY."));
    return 2;
  }
  const outDir = resolve(vaultRoot, args.out);
  await mkdir(outDir, { recursive: true });

  try {
    const report = await roundtrip(
      {
        vaultRoot,
        spine: args.spine,
        instruction: args.instruction,
        decision: args.decision,
        outDir,
        apiKey,
        log: (line) => console.log(grey(line)),
      },
      {
        writeFile: async (path, data) =>
          writeFile(path, typeof data === "string" ? data : Buffer.from(data)),
        join,
      },
    );
    if (args.json) console.log(JSON.stringify(report, null, 2));
    console.log(report.ok ? green("\nround trip complete") : red("\nround trip incomplete"));
    return report.ok ? 0 : 1;
  } catch (err) {
    const message = isSuperDocsError(err) ? `${err.message} (HTTP ${err.status})` : String(err);
    console.error(red(`round trip failed: ${message}`));
    return 1;
  }
}

async function status(): Promise<number> {
  const apiKey = process.env.SUPERDOCS_API_KEY;
  if (!apiKey) {
    console.error("Set SUPERDOCS_API_KEY first.");
    return 2;
  }
  const client = new SuperDocsClient({ apiKey, transport: nodeTransport });
  try {
    const account = await client.accountStatus();
    console.log(JSON.stringify(account, null, 2));
    return 0;
  } catch (err) {
    console.error(red(err instanceof Error ? err.message : String(err)));
    return 1;
  }
}

async function readEnvFile(root: string): Promise<string | undefined> {
  for (const candidate of [join(root, ".env"), join(process.cwd(), ".env")]) {
    if (!existsSync(candidate)) continue;
    const text = await readFile(candidate, "utf-8");
    const m = /^\s*SUPERDOCS_API_KEY\s*=\s*(.+)\s*$/m.exec(text);
    if (m) return m[1]!.trim().replace(/^["']|["']$/g, "");
  }
  return undefined;
}

function slugFilename(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "manuscript"
  );
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((err: unknown) => {
    console.error(err);
    process.exitCode = 1;
  });
