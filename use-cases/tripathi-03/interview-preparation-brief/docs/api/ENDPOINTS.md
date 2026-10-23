# API Surface

Base URL: `/api/v1`

## Health

- `GET /health` — liveness + DB ping

## Reports

- `POST /reports/generate` — assemble full professional report JSON from grounded inputs
- `POST /reports/from-brief/{brief_id}` — build report from a completed brief
- `POST /reports/export?format=pdf|docx|markdown|html|json` — export report body
- `GET /reports/{brief_id}/export?format=pdf|docx|markdown|html|json` — export completed brief

### Report sections

Cover Page · Company Overview · Role Summary · Resume Match Score · Strengths · Weaknesses · Skill Gap · Resume Improvements · Interview Questions · Evidence-backed Answers · Behavioral Answers · STAR Stories · Revision Plan · 30-60-90 Day Plan · Final Recommendations

## Questions

- `POST /questions/generate`

```json
{
  "resume_text": "...",
  "jd_text": "...",
  "company_name": "Acme",
  "company_data": { "industry": "Unknown", "mission": "Unknown" },
  "role_summary": "optional"
}
```

Returns categorized questions (technical, behavioral, company-specific, scenario, system design, coding).  
Each question includes:

- `difficulty` (`Easy` | `Medium` | `Hard`)
- `expected_answer`
- `resume_evidence` (or `"No evidence found."`)
- `missing_knowledge`
- `revision_links` (placeholders)

## Resume Analyzer

- `POST /resume/analyze` — multipart: `resume` (PDF/DOCX), optional `candidate_name`
- `POST /resume/analyze-text` — `{ "resume_text": "...", "candidate_name": "..." }`

Returns structured JSON:

```json
{
  "candidate_name": null,
  "analysis": {
    "education": [],
    "experience": [],
    "projects": [],
    "skills": [],
    "achievements": [],
    "technologies": [],
    "years_of_experience": null,
    "years_of_experience_evidence": null
  },
  "embeddings": {
    "session_id": "...",
    "document_id": "...",
    "chunk_count": 0,
    "embedding_model": "text-embedding-3-small",
    "dimensions": 1536,
    "source": "resume"
  },
  "resume_char_count": 0,
  "message": "Resume analyzed successfully"
}
```

Anti-hallucination: entries require resume evidence spans; skills/technologies must appear in text; years of experience is set only when explicitly stated (else `null`).

## Company

- `POST /company/research` — `{ "company_name": "...", "company_url": "..." }`
- `GET /company/research?company_name=...&company_url=...`

Returns structured JSON:

```json
{
  "company_name": "...",
  "industry": "Unknown",
  "products": ["Unknown"],
  "mission": "Unknown",
  "tech_stack": ["Unknown"],
  "interview_process": "Unknown",
  "engineering_culture": "Unknown",
  "latest_news": ["Unknown"],
  "tech_blogs": ["Unknown"],
  "hiring_trends": "Unknown",
  "sources": [],
  "overview": "..."
}
```

Unavailable fields are exactly `"Unknown"`. Never hallucinated — extracted only from fetched public pages.

## Documents

- `POST /documents/upload` — multipart form
  - `resume` (file, required, PDF/DOCX)
  - `job_description` (file, optional, PDF/DOCX)
  - `job_description_text` (string, optional)
  - `company_name` (string, required)
  - `company_url` (string, optional)

Parses files, stores rows in PostgreSQL, and indexes embeddings in pgvector.

## Briefs

- `POST /briefs` — `{ "session_id": "<uuid>" }`
  - Creates brief job and runs LangGraph in background
- `GET /briefs/{brief_id}/status` — status + current_step
- `GET /briefs/{brief_id}` — full structured JSON brief when completed

## LangGraph workflow

ResumeParser → JDParser → CompanyResearch → SkillGapAnalysis → QuestionGeneration → AnswerGeneration → InterviewPreparationReport
