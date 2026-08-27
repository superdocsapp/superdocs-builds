import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    rules: {
      "no-console": ["error", { allow: ["warn", "error"] }],
      "@typescript-eslint/consistent-type-imports": "error"
    }
  },
  {
    // The server and the benchmark are terminal programs: stdout is their UI.
    files: ["server/**", "bench/**"],
    rules: { "no-console": "off" }
  }
);
