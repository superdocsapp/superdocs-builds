# sdx contribution instructions

- Keep all contribution files under `extensions/Madhumasa84/sdx/`.
- Target Node.js 20+ and strict TypeScript. Use npm for dependency and script management.
- Run `npm run build`, `npm run typecheck`, `npm run lint`, and `npm test` before declaring a stage complete.
- Human results may use stdout; diagnostics, warnings, and progress always use stderr.
- `--json` must emit exactly one versioned JSON object on stdout. Never mix prose or progress into it.
- Redact API keys, tokens, authorization headers, and credential-like values from errors and logs.
- Stream large document uploads and downloads with native Node streams; never buffer or Base64-encode whole documents.
- Approval is asynchronous and deny-by-default: never apply a change unless the selected approval path explicitly authorizes it.
- Never edit DOCX XML directly.
- Validate API response bodies at runtime and verify output state before reporting success.
- Update `PROGRESS.md` after every stage and record verification evidence.
- Preserve unrelated user changes and do not modify files outside this project folder.

