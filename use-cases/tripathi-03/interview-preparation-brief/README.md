# Interview Preparation Brief

Evidence-grounded interview prep for job seekers: combine a **resume**, **job description**, and **company context** into a professional Interview Preparation Report — then polish and export it through **SuperDocs**.

Built for the **SuperDocs Round 2** assignment by **Divyanshu Tripathi** (`tripathi-03`).

## What it does

1. Upload resume (PDF/DOCX) + paste/upload JD + company name  
2. LangGraph pipeline (Groq LLM + local embeddings / pgvector) produces:
   - company overview, role summary, skill gaps  
   - categorized interview questions  
   - evidence-backed answers (`No evidence found.` when unsupported)  
   - STAR answers + 30-60-90 roadmap  
3. Local export: PDF / DOCX / Markdown / HTML  
4. **SuperDocs path (required integration):** upload → chat polish → human approve → export  

## SuperDocs features used

| Step | SuperDocs API |
|------|----------------|
| Upload report HTML | `POST /v1/documents/upload` |
| Edit / polish | `POST /v1/chat/async` (`approval_mode=ask_every_time`) |
| Approve / deny changes | `POST /v1/chat/{session_id}/approve` |
| Export DOCX/PDF | `POST /v1/documents/export` |

In the UI, open a completed report → **SuperDocs polish & export**.

## Stack

- **Frontend:** React, TypeScript, Vite, Tailwind  
- **Backend:** FastAPI, LangGraph, PostgreSQL + pgvector  
- **LLM:** Groq (`LLM_PROVIDER=groq`) — free tier  
- **Embeddings:** local hashing by default (`EMBEDDING_PROVIDER=local`)  
- **Documents:** SuperDocs cloud API for styled export / HITL edit  

## How to run

### Prerequisites

- Python 3.12+  
- Node.js 20+  
- Docker (Postgres/pgvector)  
- Free [Groq](https://console.groq.com/) API key  
- [SuperDocs](https://use.superdocs.app) API key (`sk_…`)  

### Setup

```bash
cp .env.example .env
# Fill in:
# GROQ_API_KEY=...
# SUPERDOCS_API_KEY=...
# SUPERDOCS_ENABLED=true
# LLM_PROVIDER=groq
# EMBEDDING_PROVIDER=local

docker compose up -d db

cd backend
python -m venv .venv
# Windows: .venv\Scripts\python.exe -m pip install -r requirements.txt
# Windows: .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

cd ../frontend
cp .env.example .env
npm install
npm run dev
```

- App: http://localhost:5173  
- API docs: http://localhost:8000/docs  

### Environment placeholders

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your-groq-key-here
GROQ_MODEL=llama-3.1-8b-instant
EMBEDDING_PROVIDER=local
SUPERDOCS_ENABLED=true
SUPERDOCS_API_KEY=your-superdocs-key-here
SUPERDOCS_BASE_URL=https://api.superdocs.app
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/interview_prep
```

Never commit real keys.

## Anti-hallucination

Resume-backed answers use resume-only RAG retrieval. Missing evidence returns exactly: **`No evidence found.`**

## License

Contributed under this repository’s MIT license.
