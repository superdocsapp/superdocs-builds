/**
 * Manual verification against a real vault folder and the live SuperDocs API.
 * Not part of `npm test`: it needs a key and it spends an operation.
 *
 *   npx tsx --tsconfig tests/tsconfig.json tests/live-vault.ts "<vault path>" [--approve-all]
 *
 * The key is read from the vault's own plugin data, never from a flag, and is
 * never printed.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { App, notices, setRequestHandler, Vault } from "./harness/obsidian";
import SuperDocsLivingNotePlugin from "../src/main";
import { htmlToMarkdown } from "../src/ownership";

async function main(): Promise<void> {
  const root = process.argv[2];
  if (!root) throw new Error("pass the vault path as the first argument");
  const approveAll = process.argv.includes("--approve-all");
  const dataPath = join(root, ".obsidian/plugins/superdocs-living-note/data.json");
  const data = JSON.parse(readFileSync(dataPath, "utf8")) as { settings: Record<string, unknown> };
  const key = String(data.settings.apiKey ?? "");
  if (!key) throw new Error("no API key in the vault's plugin data");

  let lastJob = "";
  setRequestHandler(async (request) => {
    const response = await fetch(request.url, { method: request.method ?? "GET", headers: request.headers, body: request.body });
    const buffer = Buffer.from(await response.arrayBuffer());
    const text = buffer.toString("utf8");
    if (request.url.includes("/v1/jobs/")) lastJob = text;
    return { status: response.status, text, arrayBuffer: buffer.buffer.slice(buffer.byteOffset, buffer.byteOffset + buffer.byteLength) };
  });
  process.on("beforeExit", () => {
    const parsed = JSON.parse(lastJob || "{}") as { status?: string; result?: { response?: string } };
    console.log("\nfinal job status:", parsed.status);
    console.log("agent said:", String(parsed.result?.response ?? "").slice(0, 1200));
  });

  const vault = new Vault(root);
  const plugin = new SuperDocsLivingNotePlugin(new App(vault) as never, {} as never);
  await plugin.onload();
  Object.assign(plugin.settings, data.settings, { autoSync: false });

  const target = plugin.settings.targetPath;
  const before = readFileSync(join(root, target), "utf8");

  plugin.showPreview = (plan) => {
    console.log("PREVIEW  regions:", plan.regions.join(", "));
    console.log("PREVIEW  fingerprint:", plan.sourceFingerprint.hash);
    console.log("PREVIEW  sources:", plan.sources.map((source) => `${source.path} (${source.score})`).join(", "));
    console.log("PREVIEW  uploaded document:\n" + plan.regionDocument.replace(/^/gm, "  | "));
  };
  plugin.review = async (changes, round, max) => {
    console.log(`\nREVIEW round ${round}/${max}: ${changes.length} proposed change(s)`);
    for (const change of changes) {
      console.log(`  - ${change.change_id} (${change.operation})`);
      console.log(`    why:  ${(change.ai_explanation ?? "").slice(0, 200)}`);
      console.log(`    now:  ${htmlToMarkdown(change.old_html ?? "").replace(/\n/g, " ").slice(0, 200)}`);
      console.log(`    new:  ${htmlToMarkdown(change.new_html ?? "").replace(/\n/g, " ").slice(0, 200)}`);
    }
    return changes.map((change) => ({ change_id: change.change_id, approved: approveAll }));
  };

  console.log("=== no-spend preview ===");
  await plugin.run(true, "manual preview");

  console.log("\n=== live sync ===");
  await plugin.run(false, "manual sync");

  const after = readFileSync(join(root, target), "utf8");
  console.log("\nNOTICES:", notices);
  const outside = (note: string) => note.replace(/<!-- superdocs:owned:start[\s\S]*?<!-- superdocs:owned:end id="[^"]+" -->/g, "<<OWNED>>");
  console.log("bytes outside the markers unchanged:", outside(before) === outside(after));
  console.log("note changed:", before !== after);
  if (before !== after) console.log("\n=== note after the run ===\n" + after);
}

void main();
