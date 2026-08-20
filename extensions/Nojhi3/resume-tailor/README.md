# Resume Tailor

Tailors a .docx resume to a job description using an LLM, applied through
SuperDoc as tracked changes — so the model never touches formatting, and you
review every edit like a normal Word redline before accepting it.

## How it preserves formatting

The model only ever sees and returns plain text per resume block (a bullet,
a summary line, and so on). The server applies each returned string as a
tracked-change replacement of that exact block via the SuperDoc CLI. Fonts,
spacing, tables, and page layout are never regenerated — only the matched
text run changes, recorded as a suggestion rather than an overwrite.

## Setup

1. `npm.cmd install`
2. Copy `.env.example` to `.env` and add your `GEMINI_API_KEY`
   (get one at https://aistudio.google.com/apikey).
3. `npm.cmd start`
4. Open http://localhost:3000

(On Windows PowerShell use `npm.cmd` — the `npm` shim resolves to a blocked
`.ps1` script. Run the smoke tests with `npm.cmd test`.)

## Verified against the installed CLI

Tested live against `@superdoc-dev/cli` 0.22.2 (contract 0.1.0): every
session-scoped command accepts `--session`; `blocks list` returns only previews
unless `--include-text` is passed; `replace` accepts a block-spanning selection
target via `--target-json` with `--change-mode tracked`; `save` takes
`--in-place`. A live run applied 11 revisions to a real resume and produced a
docx with 22 tracked insertions (`w:ins`) and 19 tracked deletions (`w:del`)
with formatting intact.

### Word-level tracked changes

Each revision is split into word-boundary regions (`server/lib/diff.js`,
longest-common-subsequence over whitespace-delimited tokens) and each region
is applied as its own tracked `replace`, right to left. Replacing a whole
block at once makes the runtime diff at the character level, fragmenting one
revision into un-reviewable mid-word edits ("using" → "us" deleted + "utiliz"
inserted, or "30" → "robust" paired from unrelated edits); region-level
replaces keep each redline readable ("Built" → "Architected", "using" →
"utilizing") while the final assembled text stays exactly the revised text.

`server/lib/superdocCli.js` isolates the CLI contract behind one small wrapper,
so if a flag name changes in a future release, that's the only file to touch.

## Swapping the LLM

Everything AI-specific lives in `server/lib/llm.js` and `server/lib/prompts.js`.
`llm.js` uses Gemini's native JSON mode (`responseMimeType: "application/json"`
plus `responseSchema`), so the API validates the response against the schema
before it's returned; swap the client and keep the same
`getResumeRevisions(jdText, blocks) -> revisions[]` shape to use a different
provider.

## License note

SuperDoc is AGPLv3, with a commercial license available for proprietary
deployments. Fine for personal use as-is — if you ship this to other
people, check which license you need at superdoc.dev.

## Project structure

```
resume-tailor/
├── server/
│   ├── index.js           — Express bootstrap (createApp().listen)
│   ├── app.js             — createApp({ sessionFactory, llm }) factory (test seam)
│   ├── routes/tailor.js   — POST /api/tailor (upload → blocks → LLM → tracked replace)
│   └── lib/
│       ├── superdocCli.js — SuperDoc CLI session wrapper
│       ├── llm.js         — Gemini call, JSON mode for structured output
│       └── prompts.js     — system/user prompt + response schema
├── public/                — upload UI + embedded SuperDoc editor
└── tests/                 — node:test smoke tests (fake session + fake LLM)
```

Full run instructions, API examples and troubleshooting: **[HOW_TO_RUN.md](HOW_TO_RUN.md)**.

Built for the SuperDocs engineering task (round 2) by Akshat Rai.
