/**
 * Copies the CLI's own read artifacts into ui/public/data/ as static JSON.
 * This is NOT a second pipeline: every file here is either read verbatim
 * from state/ (already written by `compliance --coverage/--generate/--amend`)
 * or loaded via the same config/ loaders (loadClients, loadRequirements)
 * the CLI itself uses — nothing is recomputed. Run after a CLI command, then
 * `npm run dev` in ui/ to view the result.
 */
import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadClients } from "../../src/domain/clients.js";
import { loadRequirements } from "../../src/domain/requirements.js";

const ROOT = fileURLToPath(new URL("../..", import.meta.url));
const OUT_DIR = fileURLToPath(new URL("../public/data", import.meta.url));
const EXPORTED_PACKS_SRC = path.join(ROOT, "out");
const EXPORTED_PACKS_DEST = fileURLToPath(new URL("../public/out", import.meta.url));

async function writeJson(name: string, data: unknown): Promise<void> {
  await writeFile(path.join(OUT_DIR, name), `${JSON.stringify(data, null, 2)}\n`, "utf8");
}

function isEnoent(err: unknown): boolean {
  return (err as NodeJS.ErrnoException).code === "ENOENT";
}

/** Copies a state/ JSON file verbatim if it exists; otherwise writes the fallback. */
async function copyStateFile(relPath: string, destName: string, fallback: unknown): Promise<unknown> {
  try {
    const text = await readFile(path.join(ROOT, relPath), "utf8");
    await writeFile(path.join(OUT_DIR, destName), text, "utf8");
    return JSON.parse(text);
  } catch (err) {
    if (isEnoent(err)) {
      await writeJson(destName, fallback);
      return fallback;
    }
    throw err;
  }
}

/**
 * Walks state/amendments/<REQ-ID>-<date>/. Prefers the structured event.json
 * sibling (written by --amend runs after this field existed); a batch of
 * notices from before then has no event.json, so its .md files are copied
 * in verbatim instead — never reconstructed or parsed, just read as-is, so
 * the UI shows exactly what's actually on disk either way.
 */
async function collectAmendmentEvents(): Promise<unknown[]> {
  const amendmentsDir = path.join(ROOT, "state", "amendments");
  let dirs: import("node:fs").Dirent[];
  try {
    dirs = await readdir(amendmentsDir, { withFileTypes: true });
  } catch (err) {
    if (isEnoent(err)) return [];
    throw err;
  }

  const events: unknown[] = [];
  for (const entry of dirs.sort((a, b) => a.name.localeCompare(b.name))) {
    if (!entry.isDirectory()) continue;
    const eventDir = path.join(amendmentsDir, entry.name);
    const match = /^(.+)-(\d{4}-\d{2}-\d{2})$/.exec(entry.name);

    try {
      const text = await readFile(path.join(eventDir, "event.json"), "utf8");
      events.push({ event_dir: entry.name, structured: true, event: JSON.parse(text) });
      continue;
    } catch (err) {
      if (!isEnoent(err)) throw err;
    }

    // No event.json for this batch — fall back to the raw notices.
    const files = (await readdir(eventDir)).filter((f) => f.endsWith("-notice.md"));
    const notices: { client_id: string; filename: string; content: string }[] = [];
    for (const file of files.sort()) {
      notices.push({
        client_id: file.replace(/-notice\.md$/, ""),
        filename: file,
        content: await readFile(path.join(eventDir, file), "utf8"),
      });
    }
    events.push({
      event_dir: entry.name,
      structured: false,
      requirement_id: match?.[1] ?? entry.name,
      effective_from: match?.[2] ?? null,
      notices_raw: notices,
    });
  }
  return events;
}

/** Every note file in the compliance corpus, verbatim — coverage entries cite file:line into these. */
async function collectCorpusNotes(): Promise<Record<string, string>> {
  const corpusDir = path.join(ROOT, "corpus", "ria-compliance");
  let files: string[];
  try {
    files = (await readdir(corpusDir)).filter((f) => f.endsWith(".md"));
  } catch (err) {
    if (isEnoent(err)) return {};
    throw err;
  }
  const notes: Record<string, string> = {};
  for (const file of files) {
    notes[file] = await readFile(path.join(corpusDir, file), "utf8");
  }
  return notes;
}

/**
 * Copies ../out/ into public/out/ so the browser can actually download an
 * exported pack — Vite serves everything under public/ at the site root,
 * so out/CL-01/foo.docx becomes /out/CL-01/foo.docx. The destination is
 * wiped first so a pack removed from ../out/ doesn't linger as a stale,
 * unlisted download.
 */
async function copyExportedPacks(): Promise<void> {
  await rm(EXPORTED_PACKS_DEST, { recursive: true, force: true });
  try {
    await cp(EXPORTED_PACKS_SRC, EXPORTED_PACKS_DEST, { recursive: true });
  } catch (err) {
    if (!isEnoent(err)) throw err;
  }
}

async function main(): Promise<void> {
  await mkdir(OUT_DIR, { recursive: true });

  const clients = await loadClients();
  await writeJson("clients.json", clients);

  const requirements = await loadRequirements();
  await writeJson("requirements.json", requirements);

  await copyStateFile("state/coverage.json", "coverage.json", {
    generated_at: null,
    notes_dir: null,
    summary: {},
    entries: [],
  });
  const packs = (await copyStateFile("state/packs.json", "packs.json", { generated_at: null, packs: [] })) as {
    packs: unknown[];
  };
  await copyStateFile("state/versions.json", "versions.json", { template_versions: [], client_versions: [] });
  await copyStateFile("state/consent-matrix.json", "consent-matrix.json", {
    generated_at: null,
    templates: [],
    rows: [],
  });
  await copyStateFile("state/requirements-snapshot.json", "requirements-snapshot.json", null);
  await copyStateFile("state/ledger.json", "ledger.json", null);

  const amendments = await collectAmendmentEvents();
  await writeJson("amendments.json", amendments);

  const corpusNotes = await collectCorpusNotes();
  await writeJson("corpus-notes.json", corpusNotes);

  await copyExportedPacks();

  console.log(
    `[OK] synced ${clients.length} client(s), ${requirements.length} requirement(s), ${packs.packs.length} pack(s), ${amendments.length} amendment event(s), ${Object.keys(corpusNotes).length} corpus note(s) into ui/public/data/`,
  );
}

main().catch((err: unknown) => {
  console.error(err);
  process.exitCode = 1;
});
