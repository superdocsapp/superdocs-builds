import * as fs from "fs";
import * as path from "path";
import JSZip from "jszip";

export interface ProjectInfo {
  rootFile: string;
  files: string[];
  zipBytes: Uint8Array;
  sizeBytes: number;
}

const IGNORED_DIRS = new Set([
  ".git",
  "node_modules",
  ".idea",
  ".vscode",
  ".DS_Store",
  "__pycache__",
  ".aux",
  ".synctex.gz",
]);

const IGNORED_EXTENSIONS = new Set([
  ".aux",
  ".log",
  ".out",
  ".toc",
  ".bbl",
  ".blg",
  ".lof",
  ".lot",
  ".fls",
  ".fdb_latexmk",
  ".synctex.gz",
  ".dvi",
]);

const ROOT_CANDIDATES = ["main.tex", "thesis.tex", "book.tex", "paper.tex", "manuscript.tex", "report.tex", "dissertation.tex", "index.tex"];

export function findLaTeXRoot(dir: string): string | null {
  const texFiles = listTexFiles(dir);
  if (texFiles.length === 0) return null;
  for (const f of texFiles) {
    const magic = readMagicTexRoot(path.join(dir, f));
    if (magic) return magic;
  }
  for (const candidate of ROOT_CANDIDATES) {
    if (texFiles.includes(candidate)) return candidate;
  }
  return texFiles.length === 1 ? texFiles[0] : null;
}

function listTexFiles(dir: string): string[] {
  const out: string[] = [];
  const walk = (d: string) => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      if (IGNORED_DIRS.has(entry.name)) continue;
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith(".tex")) out.push(path.relative(dir, full));
    }
  };
  walk(dir);
  return out;
}

function readMagicTexRoot(texPath: string): string | null {
  try {
    const head = fs.readFileSync(texPath, "utf8").slice(0, 4000);
    const m = head.match(/%\s*!TEX\s+root\s*=\s*(.+\.tex)/i);
    return m ? m[1].trim() : null;
  } catch {
    return null;
  }
}

export async function buildProjectZip(dir: string, rootFile: string): Promise<ProjectInfo> {
  const files: string[] = [];
  const walk = (d: string) => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      if (entry.name === ".git" || entry.name === "node_modules") continue;
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name === ".DS_Store") continue;
      else if (IGNORED_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) continue;
      else files.push(path.relative(dir, full));
    }
  };
  walk(dir);
  files.sort();

  const zip = new JSZip();
  for (const rel of files) {
    zip.file(rel, fs.readFileSync(path.join(dir, rel)));
  }
  const zipBytes = await zip.generateAsync({ type: "uint8array" });
  return {
    rootFile,
    files,
    zipBytes,
    sizeBytes: zipBytes.byteLength,
  };
}
