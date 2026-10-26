/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_ANALYZER_API_URL?: string;
  readonly VITE_EDITOR_API_URL?: string;
  readonly VITE_INGESTOR_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}