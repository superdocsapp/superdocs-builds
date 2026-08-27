# Build A — Revision Bars & Controlled Document Generator

Aviation-grade revision apparatus for controlled documents. After an editing session, the app automatically produces:

1. **Change bars in the margin** next to every altered paragraph (and nowhere else).
2. **Revision-record table** (revision number, date, affected pages/sections, summary of change).
3. **List of Effective Pages (LEP)** mapping changed sections to `Revised` and others to `Original`.
4. **Highlights-of-change summary** for flight and maintenance crew.
5. **Running headers and footers** stamped with revision identity (`Revision {num} — {date}`) and dynamic page numbers (`Page X of Y`).
6. **Controlled PDF export** with automated PyMuPDF verification harness.

## Architecture

```
React Frontend (Vite + TypeScript, port 5173)
    ↕ REST API
Python FastAPI Sidecar (server.py, port 8000)
    ↕ HTTP
SuperDocs REST API (api.superdocs.app)
```

## Setup & Testing

```bash
# Sidecar backend
cd sidecar
python -m venv .venv
# Activate virtual environment
pip install -e ".[dev]"
pytest  # Runs 41 unit tests

# Start sidecar server
uvicorn server:app --reload --port 8000

# Frontend (separate terminal)
cd ../frontend
npm install
npm run dev  # http://localhost:5173
```

## Operation Budget

- **Step 1 (Load + Edit + Diff + Revision Apparatus)**: 1 op (combined turn).
- **Step 2 (Header / Footer Stamping)**: 1 op.
- **Step 3 (Export PDF)**: 0 ops.
- **Total**: Exactly **2 ops** per revision cycle.

