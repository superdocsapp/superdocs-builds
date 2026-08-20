# How to run — Resume Tailor

Express app that tailors a `.docx` resume to a job description via Gemini,
applying every change as a **SuperDoc tracked change** so formatting is never
regenerated and you review a Word redline before accepting.

All commands run from this project root.

## A. Prerequisites

- Node 18+ (verified on Node 24).
- A Gemini API key (`AIza...` from https://aistudio.google.com/apikey).
- Internet access (the UI loads the SuperDoc editor from the jsDelivr CDN;
  the server needs the Gemini API).

```bash
npm install                          # installs @superdoc-dev/cli + @google/generative-ai
cp .env.example .env                 # fill in GEMINI_API_KEY (and PORT if 3000 is taken)
```

> On Windows PowerShell, `npm` resolves to a blocked `npm.ps1` script. Use
> **`npm.cmd`** instead (`npm.cmd install`, `npm.cmd start`, `npm.cmd test`).

## B. Run the server

```bash
npm.cmd start                        # or: npm.cmd run dev (auto-restart on change)
# Resume Tailor running at http://localhost:3000
```

1. Open http://localhost:3000.
2. Upload a `.docx` resume, paste the job description.
3. Click **Tailor resume** — the tailored file opens in the embedded editor as a
   tracked-changes redline, with each revision listed (location, reason,
   original → revised). Reject or keep them, then **Download .docx**.

## C. Drive the API directly

```bash
curl -X POST http://localhost:3000/api/tailor \
  -F "resume=@path/to/resume.docx;type=application/vnd.openxmlformats-officedocument.wordprocessingml.document" \
  -F "jobDescription=<path/to/job-description.txt" \
  -o response.json
```

Returns `{ "docx": "<base64 of the tailored .docx>", "revisions": [...] }`.
Each revision carries `nodeId`, `original`, `revisedText`, `reason`, `line`,
`page`, and `lengthFlag` (true when the revision's length changed drastically —
worth a second look).

Verified live: 9 revisions applied to a real resume; the returned docx contained
**31 tracked insertions (`w:ins`) and 33 tracked deletions (`w:del`)**, with 322
run-property nodes intact (formatting preserved).

## D. Smoke tests (offline, no API calls)

```bash
npm.cmd test                         # node --test → 6 tests
```

Covers: 400 on missing inputs, the happy path (tracked replace + save + close,
revision metadata), the session lifecycle, skipping revisions for unknown
`nodeId`s, and a clean 500 + session close when the LLM throws. Uses fake
session + fake LLM — no Gemini or SuperDoc calls.

## E. Verify the installed SuperDoc CLI (optional)

The CLI wrapper (`server/lib/superdocCli.js`) runs the locally installed
`@superdoc-dev/cli` directly (not `npx superdoc`, which resolves the *browser
editor* package). The flags it uses are verified against the installed version:

```bash
node node_modules/@superdoc-dev/cli/dist/index.js describe command open
node node_modules/@superdoc-dev/cli/dist/index.js describe command "blocks list"
node node_modules/@superdoc-dev/cli/dist/index.js describe command replace
node node_modules/@superdoc-dev/cli/dist/index.js describe command save
node node_modules/@superdoc-dev/cli/dist/index.js describe command close
```

Verified on CLI 0.22.2 (contract 0.1.0): every command accepts `--session`;
`blocks list` needs `--include-text` for full block text; `replace` takes
`--target-json` (a block-spanning selection target), `--text` and
`--change-mode tracked`; `save` takes `--in-place`. If your installed version
differs, `server/lib/superdocCli.js` is the only file that needs adjusting.

## F. Troubleshooting

- **`npm.ps1` cannot be loaded** — execution policy; use `npm.cmd` (see A).
- **UI editor missing / blank right panel** — the editor loads from
  `https://cdn.jsdelivr.net/npm/superdoc/...`; a blocked CDN or offline network
  breaks it. The API still works fine.
- **`401`/`403` from Gemini** — the key in `.env` is wrong or expired; replace
  `GEMINI_API_KEY` with a fresh `AIza...` key.
- **Tailoring failed (500)** — check the server console for the CLI/Gemini error
  and confirm the resume is a real `.docx` (not a renamed `.zip` or `.doc`).
- **Secrets** — `.env` is gitignored; never commit it. `.env.example` must only
  contain placeholders.