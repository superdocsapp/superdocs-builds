# Confluence in-page AI edit and review

Built by **Jaskirat Singh** for the SuperDocs task.

Edits the Confluence page you are on instead of exporting it away. Select a section, give an instruction, review SuperDocs diffs inline, send a named approver if you want a second gate, then write **only accepted ranges** back as ADF. Tables, code blocks, and macros are placeholders SuperDocs is not allowed to rewrite. Space normalisation is a page-by-page queue. Publish for people who never open Confluence is a branded PDF via SuperDocs export.

## What SuperDocs is used for

- upload / `document_html`
- `POST /v1/chat/async` with `approval_mode=ask_every_time`
- approve / reject each proposed change
- `POST /v1/documents/export` (PDF)

Proposed-change payloads are parsed twice (JSON string → object). Large edits that pause with `awaiting_kind=continue_prompt` are resumed, not retried as a new job.

## Run (sidecar demo, no Forge required)

```bash
cd extensions/jaskiringg/confluence-ai
cp .env.example .env   # put SUPERDOCS_API_KEY here
npm install
npm --prefix static/ui install
npm run ui:build
npm run sidecar
```

Open http://127.0.0.1:8787 — demo IT policy page with a table + code block.

To hit a real Confluence Cloud site from the sidecar, set `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`, and a page id.

## Run (Forge, sideload)

1. Create a free Confluence Cloud site.
2. `npm i -g @forge/cli` then `forge login`.
3. In this folder: `forge register` (replaces the placeholder `app.id` in `manifest.yml`).
4. `forge variables set SUPERDOCS_API_KEY`
5. `FORGE=1 npm --prefix static/ui run build && forge deploy && forge install`

Page action: **SuperDocs AI edit**. Space page: **SuperDocs space queue**.

Marketplace listing is out of scope; sideload is enough.

## Honest limits

- Native Confluence **Publish** cannot be fully intercepted from a content-action modal. We block **our** write-back until the named approver accepts, and store that state on a content property. That is the gate we can actually keep.
- Sidecar without Confluence credentials uses a synthetic page so the SuperDocs loop can be demoed.
- ADF mapping covers headings, paragraphs, lists, quotes. Unknown/opaque nodes stay byte-stable on the original ADF.

## Tests

```bash
npm test
```

No live SuperDocs key required for unit tests.
