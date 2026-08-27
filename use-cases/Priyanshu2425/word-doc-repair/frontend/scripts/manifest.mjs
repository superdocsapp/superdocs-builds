/**
 * Records what the committed bundle was built from.
 *
 * The bundle is committed so a reviewer with no Node still gets the product.
 * The cost of that decision is that the file can fall behind its source and
 * nobody notices, so the build writes a hash of every source file and a pytest
 * recomputes it. Stale bundle, failed build.
 */
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";

const root = process.cwd();
const roots = ["src", "index.html", "vite.config.ts", "package.json"];

function walk(path, out = []) {
  const s = statSync(path);
  if (s.isDirectory()) {
    for (const entry of readdirSync(path).sort()) {
      if (entry === "test" || entry === "fixtures" || entry === "node_modules") continue;
      walk(join(path, entry), out);
    }
  } else {
    out.push(path);
  }
  return out;
}

const files = roots.flatMap((r) => walk(join(root, r)));
const hash = createHash("sha256");
for (const file of files.sort()) {
  hash.update(relative(root, file));
  hash.update(readFileSync(file));
}

writeFileSync(
  join(root, "bundle-manifest.json"),
  JSON.stringify({ sources: hash.digest("hex"), files: files.length }, null, 2) + "\n",
);
console.log("bundle-manifest written over", files.length, "source files");
