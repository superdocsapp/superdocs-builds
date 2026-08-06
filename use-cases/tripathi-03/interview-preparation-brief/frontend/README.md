# Frontend — Interview Preparation Brief

Modern React + TypeScript UI with TailwindCSS, Shadcn-style primitives, React Query, Axios, and React Router.

## Pages

| Route | Page |
|-------|------|
| `/` | Home |
| `/upload` | Upload Resume |
| `/job-description` | Paste Job Description |
| `/company` | Company Search + generate |
| `/reports/:briefId` | Interview Report |
| `/history` | History |

## Reusable components

- `DragDropUpload`
- `RichTextEditor`
- `QuestionCard`
- `SkillGapCharts`
- `LoadingSpinner` / `LoadingOverlay`
- `ProgressStepper`
- `PdfExportButton`
- Dark mode toggle

## Run

```bash
cd frontend
npm install
npm run dev
```

Set API base URL (optional):

```bash
# .env
VITE_API_BASE_URL=http://localhost:8000/api/v1
```
