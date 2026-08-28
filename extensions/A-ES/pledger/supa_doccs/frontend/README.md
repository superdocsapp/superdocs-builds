# Frontend

React + Vite review interface for the approval gate: reviewers inspect pending
findings/conflicts with their source citations and approve or reject them
individually. Talks to the FastAPI backend at `localhost:8000` (stateless; runs
as a separate Vite dev server, not containerized).

## Commands

```bash
npm install        # first time only
npm run dev        # dev server at http://localhost:5173 (backend must be up: make demo)
npm test           # Vitest unit tests
npm run lint       # ESLint
npm run build      # type-check (tsc -b) + production build to dist/
```

End-to-end tests use Playwright (`e2e/`, config in `playwright.config.ts`,
reports in `playwright-report/`).
