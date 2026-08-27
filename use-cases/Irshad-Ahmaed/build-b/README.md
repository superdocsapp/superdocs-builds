# Build B — Build vs Buy ROI Calculator

Self-serve TCO calculator comparing in-house AI document pipeline costs against SuperDocs.

- **Interactive Inputs**: Monthly document volume, initial engineering build hours, loaded hourly rate, and infrastructure overhead.
- **Live Recompute**: Real-time client-side calculation with instant updates.
- **Exact Number Invariance**: Downloads a real branded executive PDF report via the SuperDocs export API where every figure matches the on-screen numbers to the penny ($26,000 savings, 42.0-month in-house break-even, Immediate Day-1 payback).
- **Latency Optimized**: Uses structured HTML pre-seeding (`build_report_template`) to generate PDFs in **~2–4s** instead of 20s.

## Architecture

Build B integrates directly with the unified FastAPI sidecar server. The `/api/export-report` endpoint imports `build_b.calculator` to run the ROI model and trigger export.

```
React Frontend (Vite + TypeScript, port 5174)
    ↕ REST API (proxied to localhost:8000)
Python FastAPI Sidecar (server.py, port 8000)
    ↕ HTTP
build_b.calculator → SuperDocs REST API (api.superdocs.app)
```

## Calculator Financial Model

- **In-House Build Cost**: 
  - CapEx: `Engineering Hours × Hourly Cost` (e.g., $14,000 for 200 hrs @ $70/hr).
  - OpEx: Maintenance (20% of build/year = $2,800/yr) + Infrastructure ($120/mo = $1,440/yr).
  - 3-Year Total: $26,720.00.
- **SuperDocs Plus (Buy)**: 
  - CapEx: $0.00.
  - OpEx: $20/month ($240/year).
  - 3-Year Total: $720.00.
- **Projected Savings**: $26,000.00 (97.3% reduction).
- **Payback Period**: Immediate (Day 1 — $0 CapEx).
- **In-House Break-Even Point**: 42.0 Months (to recoup $14k initial dev investment).

## Setup & Testing

```bash
# Sidecar backend (from repo root or build-a/sidecar)
cd ../build-a/sidecar
pytest ../../build-b/sidecar/tests -q  # Runs 20 unit tests

# Frontend
cd ../../build-b/frontend
npm install
npm run dev  # http://localhost:5174
```

## Operation Budget

1 op per report session (PDF export is free). Free tier allows 500 reports/month.

