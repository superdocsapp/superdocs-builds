import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

/**
 * Vite config, with one Office-shaped wrinkle.
 *
 * Word will not load add-in content over plain HTTP, even from localhost, so the
 * dev server has to serve HTTPS before the task pane can be sideloaded. The
 * certificate comes from office-addin-dev-certs, which is the supported way to
 * get a locally-trusted one.
 *
 * Those certs are not required to work on TokenScope - the standalone demo is
 * plain HTTP and most development never opens Word - so their absence is a log
 * line and a fallback, not an error. Run `npm run word:certs` to install them.
 */
async function httpsOptions(): Promise<{ cert: Buffer; key: Buffer } | undefined> {
  try {
    const certs = await import("office-addin-dev-certs");

    // verifyCertificates() only reports. getHttpsServerOptions() *generates and
    // installs* a CA into the user's trust store as a side effect, so it is only
    // reached once the certificate is already there. Starting a dev server must
    // never quietly change what a machine trusts; `npm run word:certs` is the
    // explicit opt-in for that.
    if (!(await certs.verifyCertificates())) {
      console.warn(
        "[tokenscope] no Office dev certificate installed; serving HTTP.\n" +
          "            Word requires HTTPS - run `npm run word:certs` before sideloading."
      );

      return undefined;
    }

    const { cert, key } = await certs.getHttpsServerOptions();

    return { cert, key };
  } catch {
    console.warn("[tokenscope] could not read Office dev certificates; serving HTTP.");
    return undefined;
  }
}

export default defineConfig(async () => {
  const https = await httpsOptions();

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // The manifest names this exact origin, so a shifted port breaks sideloading.
      strictPort: true,
      ...(https === undefined ? {} : { https }),
      proxy: { "/api": "http://127.0.0.1:8787" }
    },
    build: { outDir: "dist", sourcemap: true },
    test: {
      environment: "node",
      include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"]
    }
  };
});
