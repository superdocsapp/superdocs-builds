# System Design — Interview Preparation Brief

## Agent Workflow

```
ResumeParser
    ↓
JDParser
    ↓
CompanyResearch
    ↓
SkillGapAnalysis
    ↓
QuestionGeneration
    ↓
AnswerGeneration
    ↓
InterviewPreparationReport
```

Each node is an independent `BaseNode` with typed Input, Output, and Validation.
Shared `BriefState` is passed between nodes. See `LANGGRAPH_WORKFLOW.md`.

## Data Flow

1. Upload resume (PDF/DOCX) + JD (file or text) + company name
2. Parse with PyMuPDF / python-docx
3. Chunk + embed into PostgreSQL pgvector (`resume`, `jd`, later `company`)
4. Start brief job → LangGraph runs in background
5. Answer Generator retrieves **resume-only** chunks per question
6. Evidence guard forces fallback when no spans exist
7. Report Generator returns structured Pydantic/JSON brief

## Module Map

| Package | Responsibility |
|---------|----------------|
| `api/` | HTTP adapters + Depends() DI |
| `services/parsers` | PDF/DOCX → text |
| `services/rag` | chunk, embed, vector store, retrieve |
| `services/company` | URL fetch + grounded overview |
| `services/brief` | ingest + brief lifecycle |
| `agents/` | LangGraph graph, nodes, prompts, runner |
| `models/` | SQLAlchemy ORM |
| `schemas/` | Pydantic API + agent outputs |
| `database/` | async engine, sessions, init |
| `utils/` | evidence guard, JSON parse |
| `core/` | settings, logging, exceptions |

## Anti-Hallucination

- Resume answers: retriever filter `source=resume`
- Missing evidence → `No evidence found.`
- Company claims grounded on fetched URL text when available
- Skill matches require resume evidence quotes
