import { build } from "esbuild";
import { copyFileSync, mkdirSync } from "fs";

const watch = process.argv.includes("--watch");

async function main() {
  const common = {
    bundle: true,
    sourcemap: true,
    format: "cjs",
    platform: "node",
    external: ["vscode"],
    logLevel: "info",
  };
  await build({
    ...common,
    ...(watch ? { watch: true } : {}),
    entryPoints: ["src/extension.ts"],
    outfile: "dist/extension.js",
  });
  await build({
    ...common,
    ...(watch ? { watch: true } : {}),
    entryPoints: ["src/webview/app.tsx"],
    outfile: "dist/webview/app.js",
    loader: { ".tsx": "tsx" },
    define: { "process.env.NODE_ENV": '"production"' },
  });
  mkdirSync("dist/media", { recursive: true });
  copyFileSync("src/webview/app.css", "dist/media/app.css");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
