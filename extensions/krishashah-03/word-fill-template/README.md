# AI Word Template Filler

An AI-powered Microsoft Word Add-in that fills an existing Word template from
natural language, a pasted email, bullet points, JSON, or CSV - always
reviewed by the user before anything touches the document.

MVP scope: **HR Employee Salary Structure**. The backend pipeline (parsing,
normalization, gap detection, condition evaluation, template resolution) is
schema-driven and generic, so future template categories (Invoice, NDA, Offer
Letter, ...) only need a new `templates/<category>/schema.json` - no changes
to the core engine.

## Architecture

![Architecture diagram](./architecture-diagram.png)

```
Word document/template
        |
React Word Add-in (task pane)
        |
User provides input (text / JSON / CSV)
        |
FastAPI backend
        |
Input parser (deterministic for JSON/CSV, AI for free text)
        |
AI extraction (OpenRouter) - only for unstructured text
        |
Normalization -> Validation -> Gap detection -> Condition engine
        |
Proposed changes
        |
React Review UI  <-- user reviews before anything is applied
        |
User clicks "Apply to Word"
        |
Office.js applies only the approved, ready fields to the open document
```

The document is never modified silently. Fields with no value are shown as
gaps and left untouched; the user can fill them in and revalidate before
applying.

## Project layout

```
word-fill-template/
├── backend/                 FastAPI app (Python)
│   ├── app/
│   │   ├── main.py          App wiring, CORS, template seeding on startup
│   │   ├── api/              extraction.py, templates.py, documents.py
│   │   ├── services/         normalization, validation, gap detection,
│   │   │                     condition engine, template engine, AI extractor
│   │   ├── parsers/          json_parser.py, csv_parser.py, text_parser.py
│   │   ├── db/                SQLAlchemy models + session
│   │   └── schemas/           Pydantic request/response models
│   ├── tests/                pytest suite (63 tests)
│   ├── schema.sql            PostgreSQL schema (source of truth)
│   └── requirements.txt
├── frontend/                 React + Vite Word Add-in (JavaScript/JSX only)
│   ├── public/manifest.xml   Office Add-in manifest
│   ├── public/icons/         16/32/80px taskpane icons
│   └── src/
│       ├── components/       InputPanel, RecordPreview, ReviewPanel,
│       │                     GapList, LoadingState
│       └── services/          api.js (fetch), wordApi.js (Office.js)
├── templates/hr/              salary_structure.docx + schema.json
├── uploads/                   local file storage (gitignored)
└── generated/                 local file storage (gitignored)
```

## 1. Installation

**Backend** (from `backend/`):

```bash
python -m venv venv
venv\Scripts\activate            # Windows
source venv/bin/activate         # macOS/Linux
pip install -r requirements.txt
```

**Frontend** (from `frontend/`):

```bash
npm install
```

## 2. PostgreSQL setup

Requires a local PostgreSQL server (no Docker). Create the database and load
the schema:

```bash
createdb word_ai_template_filler
psql -d word_ai_template_filler -f backend/schema.sql
```

(`schema.sql` includes `CREATE EXTENSION IF NOT EXISTS "pgcrypto"` for
`gen_random_uuid()`.)

The `templates/hr/schema.json` template is registered into the `templates`
and `template_conditions` tables automatically the first time the backend
starts - no manual seed step needed.

## 3. Environment variables

Copy `backend/.env.example` to `backend/.env` and fill in your values:

```
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/word_ai_template_filler

OPENROUTER_API_KEY=
OPENROUTER_MODEL=openrouter/free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=30

CORS_ORIGINS=["*"]
```

`OPENROUTER_API_KEY` is only required for **natural language / email /
bullet-point** input - JSON and CSV input never call OpenRouter. The key is
read only on the backend and is never sent to the frontend.

## 4. Backend startup

```bash
cd backend
venv\Scripts\activate     # if not already active
uvicorn app.main:app --reload --port 8000
```

Health check: `GET http://localhost:8000/api/health`
Interactive docs: `http://localhost:8000/docs`

## 5. Frontend startup

```bash
cd frontend
npm run dev
```

By default this serves the task pane at `http://localhost:3000` (or the next
free port). Word requires **HTTPS** to load a taskpane, so install a trusted
local dev certificate once:

```bash
npx office-addin-dev-certs install
```

`vite.config.js` automatically picks up that certificate (from
`~/.office-addin-dev-certs/`) and serves over HTTPS once it exists; without
it, the dev server falls back to plain HTTP (fine for testing the UI in a
regular browser tab, but Word itself will refuse to load it).

## 6. Word Add-in setup (sideloading)

1. Make sure the frontend dev server is running over HTTPS on port 3000.
2. In Word: **Insert -> Add-ins -> My Add-ins -> Upload My Add-in**, and
   select `frontend/public/manifest.xml`.
   - On Windows, you can also copy `manifest.xml` into your **shared folder**
     catalog and sideload from there - see Microsoft's
     [sideloading docs](https://learn.microsoft.com/office/dev/add-ins/testing/create-a-network-shared-folder-catalog-for-task-pane-and-content-add-ins)
     if `Upload My Add-in` isn't available in your build.
3. Open the **AI Document Filler** task pane from the ribbon.
4. Open (or create) a Word document containing the placeholders from
   `templates/hr/salary_structure.docx` (or open that file directly).

## Example inputs

**Natural language:**

```
Create salary structure for Rahul Patel. He is joining on 1 September 2026
as a Software Engineer. His CTC is 8 LPA. His notice period is 30 days.
He is based in Ahmedabad and works remotely.
```

**JSON:**

```json
{
  "name": "Rahul Patel",
  "designation": "Software Engineer",
  "joining_date": "2026-09-01",
  "ctc": "8 LPA",
  "notice_period": 30,
  "location": "Ahmedabad",
  "remote": true
}
```

**CSV:**

```csv
name,designation,joining_date,ctc,notice_period,location,remote
Rahul Patel,Software Engineer,2026-09-01,8 LPA,30,Ahmedabad,Yes
```

Bare keys like `name` or `ctc` are matched to the template's schema fields
(`employee.name`, `employee.ctc`, ...) automatically - dotted keys work too.

## Success scenario

1. Paste the natural language example above into the task pane and click
   **Extract Information**.
2. The backend parses it (via OpenRouter for text input), normalizes dates
   ("1 September 2026" -> `2026-09-01`), salary ("8 LPA" -> `800000`), and
   booleans ("remotely" -> `true`), detects gaps, and evaluates the
   `employee.remote` condition.
3. The Review panel shows every proposed change plus whether the
   `REMOTE WORK ARRANGEMENT` section will be included or removed.
4. If `notice_period` were omitted, it would show under **Missing
   Information** instead of being guessed - fill it in and click
   **Revalidate**.
5. Click **Apply to Word** - only fields marked "Ready" are written into the
   open document, via ordinary `Word.run()` edits (so Word's normal undo
   still works).

## Test commands

```bash
cd backend
venv\Scripts\activate
pytest -q
```

Covers: JSON/CSV parsing (valid + invalid), natural language / email /
bullet-point extraction pipelines (AI call mocked), salary/date/boolean
normalization, missing-field gap detection, condition evaluation (include /
exclude / unresolved), template field resolution, and malformed/timeout/
error handling for the OpenRouter integration.

```bash
cd frontend
npm run lint
npm run build
```

## Known limitations

- **MVP scope is HR salary structure only.** The engine is generic, but no
  other template categories are wired up yet.
- **CSV/record-count:** the CSV parser and `/api/document-runs` flow handle
  one record per request (matches the single-document review flow in the
  spec); batch generation isn't implemented.
- **Condition engine markers:** applying conditional sections in Word relies
  on `{{#if field}}` / `{{/if}}` each being findable via `Range.search()`;
  hand-edited templates that break these markers across multiple runs (e.g.
  by applying formatting mid-placeholder) may not resolve correctly - this
  is a known constraint of the Word JS API's text search, not the condition
  engine itself (which is fully deterministic and unit tested).
- **`@microsoft/office-js` is deprecated** upstream and has no
  bundler-compatible entry point (no `main`/`exports` field), so it's listed
  as a dependency but Office.js is actually loaded via Microsoft's CDN
  `<script>` tag in `index.html`, per Microsoft's own current guidance.
- **AI extraction quality** depends on the configured OpenRouter model;
  `OPENROUTER_MODEL=openrouter/free` is a placeholder - pick an actual
  available free-tier model ID from OpenRouter for real use.
- **Auth:** there's no login/session layer - `created_by` fields exist in
  the schema but nothing populates them yet.
- **Live DB/API integration wasn't exercised in this environment** (no
  PostgreSQL credentials available here) - the full pytest suite (parsers,
  normalization, gaps, conditions, template engine, AI extractor, and a
  simulated end-to-end pipeline for text/email/bullet input) passes, and the
  FastAPI app's route table and OpenAPI schema were verified to match the
  spec, but you should run `pytest` and a manual `/docs` smoke test against
  your own Postgres instance before relying on it.
