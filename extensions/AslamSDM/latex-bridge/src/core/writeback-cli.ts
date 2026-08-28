import * as fs from "fs";
import * as path from "path";
import { TexSegment, segmentize } from "./writeback";
import {
  Change,
  ProjectFiles,
  buildAlignment,
  planPatches,
  applyPatches,
} from "./align";

export interface WriteBackOutcome {
  files: Map<string, string>;
  applied: { changeId: string; file: string; start: number; end: number }[];
  unresolved: string[];
}

export async function writeBackToProject(
  projectDir: string,
  rootFile: string,
  changes: Change[]
): Promise<WriteBackOutcome> {
  const files = readTexFiles(projectDir);
  const segments = new Map<string, TexSegment[]>();
  for (const [rel, content] of Object.entries(files)) {
    segments.set(rel, segmentize(content));
  }
  const plan = buildAlignment(files, segments);
  const { patches, unresolved } = planPatches(changes, plan, files);
  const result = applyPatches(files, patches);
  return {
    files: result.files,
    applied: result.applied.map((p) => ({
      changeId: p.changeId,
      file: p.file,
      start: p.start,
      end: p.end,
    })),
    unresolved: unresolved.map((c) => c.change_id),
  };
}

function readTexFiles(projectDir: string): ProjectFiles {
  const out: ProjectFiles = {};
  const walk = (d: string) => {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      if (entry.name === ".git" || entry.name === "node_modules") continue;
      const full = path.join(d, entry.name);
      if (entry.isDirectory()) {
        walk(full);
      } else if (entry.name.endsWith(".tex")) {
        out[path.relative(projectDir, full)] = fs.readFileSync(full, "utf8");
      }
    }
  };
  walk(projectDir);
  return out;
}
