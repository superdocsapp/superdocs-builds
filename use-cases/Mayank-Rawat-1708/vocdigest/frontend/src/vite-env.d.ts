/// <reference types="vite/client" />

/**
 * @file src/vite-env.d.ts
 * @description Ambient types for Vite's import.meta.env. Declaring the app's own
 *   variables gives autocomplete and stops a typo in an env key passing typecheck.
 */
interface ImportMetaEnv {
  /** Backend base URL. Defaults to /api, which Vite proxies in dev. */
  readonly VITE_API_BASE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
