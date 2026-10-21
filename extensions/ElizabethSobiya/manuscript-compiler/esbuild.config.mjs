import esbuild from "esbuild";
import process from "node:process";

const production = process.argv.includes("production");

const banner = `/*
Manuscript Compiler for Obsidian — built for the SuperDocs task by Elizabeth Sobiya.
This file is generated; edit the sources in src/ instead.
*/`;

/** The Obsidian plugin bundle: one main.js next to manifest.json. */
const plugin = {
  entryPoints: ["src/main.ts"],
  bundle: true,
  outfile: "main.js",
  format: "cjs",
  target: "es2022",
  platform: "browser",
  logLevel: "info",
  sourcemap: production ? false : "inline",
  minify: production,
  treeShaking: true,
  banner: { js: banner },
  external: [
    "obsidian",
    "electron",
    "@codemirror/autocomplete",
    "@codemirror/collab",
    "@codemirror/commands",
    "@codemirror/language",
    "@codemirror/lint",
    "@codemirror/search",
    "@codemirror/state",
    "@codemirror/view",
    "@lezer/common",
    "@lezer/highlight",
    "@lezer/lr",
  ],
};

/** The headless CLI: same core, node platform, real filesystem. */
const cli = {
  entryPoints: ["src/cli/index.ts"],
  bundle: true,
  outfile: "dist/cli.mjs",
  format: "esm",
  target: "node20",
  platform: "node",
  logLevel: "info",
  sourcemap: false,
  minify: false,
  banner: { js: `#!/usr/bin/env node\n${banner}` },
  external: ["node:*"],
};

if (production) {
  await Promise.all([esbuild.build(plugin), esbuild.build(cli)]);
} else {
  const contexts = await Promise.all([esbuild.context(plugin), esbuild.context(cli)]);
  await Promise.all(contexts.map((c) => c.watch()));
}
