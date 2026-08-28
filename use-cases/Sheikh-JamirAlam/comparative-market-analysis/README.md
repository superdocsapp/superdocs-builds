# Comparative Market Analysis Generator

This project generates a polished, branded Comparative Market Analysis (CMA) document for real estate agents. An agent provides a subject property, four or more comparable properties, and their branding. The application calculates a suggested price range, builds the document from an HTML template, and uses SuperDocs to produce a styled PDF, DOCX, or HTML document.

## Problem statement

Real estate agents often need to turn scattered property information into a clear, homeowner-friendly listing presentation. Spreadsheet-style data dumps are difficult for sellers to understand and do not communicate the agent's recommendation effectively. This application provides a repeatable workflow for turning property data into a branded CMA with a subject-property summary, photos, comparable-sales table, pricing rationale, and suggested price range.

The property data in this repository is synthetic fixture data. No MLS integration is required.

## Prerequisites

- Python 3.14 or newer
- [`uv`](https://docs.astral.sh/uv/)
- Node.js and Bun for the frontend
- A SuperDocs account and API key

Create a local environment file by copying `.env.example` to `.env` and add your key:

```text
SUPERDOCS_API_KEY="sk_your_api_key_here"
```

Keep the real key out of source control.

## Run a sample from a fixture

From the repository root:

```powershell
cd backend
uv sync
uv run python scripts/run_sample.py --fixture suburban_single_family.json
```

The generated file is saved in `backend/output/`. Other available fixtures (find them in `backend/fixtures/`) are:

```text
condo.json
luxury.json
```

You can choose `pdf`, `docx`, or `html`:

```powershell
uv run python scripts/run_sample.py --fixture condo.json --format docx
```

The script loads the selected JSON fixture (these are all generated data), applies the saved HTML template, sends the document workflow to SuperDocs, and exports the result.

## Use your own dataset

Use two terminals.

In terminal 1, start the FastAPI backend:

```powershell
cd backend
uv sync
uv run uvicorn cma.api:app --reload --port 8000
```

The API is available at `http://localhost:8000`.

In terminal 2, install and start the frontend:

```powershell
cd frontend
bun install
bun run dev
```

Open the local URL printed by Vite, usually `http://localhost:5173`. Enter your branding, subject property, and at least four comparable properties, then submit the form.

You can add your own property data directly in the web form. The frontend sends it to the backend, which creates the CMA using the same SuperDocs workflow as the sample script.

Document generation may take a while — large or complex requests can take from several seconds to several minutes depending on SuperDocs response time. When the request completes, view the generated document in [use.superdocs.app](https://use.superdocs.app).

## Run tests

From `backend/`:

```powershell
uv run pytest -v
```

The tests currently cover the price-range heuristic, including normal and edge cases. If `uv` reports a local cache-permission error, run pytest directly through the existing virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

## Project structure

```text
backend/
  cma/              Domain models, pricing, pipeline, API, and SuperDocs client
  fixtures/         Synthetic sample property datasets
  scripts/          Command-line sample runner
  templates/        Saved HTML document template
  tests/            Backend tests
  output/           Generated documents
frontend/           React/Vite data-entry form
planning.md         Project planning and implementation notes
superdocs.txt       SuperDocs API and integration reference
```

## Pricing heuristic and limitations

The suggested price range is based on comparable-property price-per-square-foot values and is intended as a simple demonstration heuristic. It is not an appraisal, valuation, or substitute for local market expertise. The application uses synthetic data and public placeholder photo URLs; it does not connect to MLS data.
