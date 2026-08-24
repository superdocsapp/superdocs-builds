import esbuild from "esbuild";
import { cp, mkdir } from "node:fs/promises";

const production = process.argv[2] === "production";
await mkdir(".build", { recursive: true });

const options = {
  entryPoints: ["src/main.ts"],
  bundle: true,
  external: ["obsidian"],
  format: "cjs",
  target: "es2020",
  sourcemap: production ? false : "inline",
  minify: production,
  outfile: "main.js",
  logLevel: "info",
};

if (production) {
  await esbuild.build(options);
} else {
  const context = await esbuild.context(options);
  await context.watch();
  console.log("watching for changes");
}

await cp("manifest.json", ".build/manifest.json");
