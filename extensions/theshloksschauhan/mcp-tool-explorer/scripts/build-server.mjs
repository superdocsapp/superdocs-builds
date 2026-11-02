import * as esbuild from "esbuild";

await esbuild.build({
  entryPoints: ["src/server/index.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  outfile: "dist/server/index.js",
  packages: "external",
  sourcemap: true,
});
