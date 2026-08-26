# Resume Bulk Normaliser

Converts raw, unstructured resume text into a consistent structured format using SuperDocs.

## What it does

Each resume goes through the full SuperDocs minimum contract — upload, chat, approve, export — and comes back as a structured JSON object. Failures are reported per-file; the batch always returns 200 so one bad resume never hides the rest.

The service processes resumes sequentially (no concurrent sessions) to stay within API rate limits. Set `approval_mode: ask_every_time` so the HITL gate is exercised on every normalisation; changes are auto-approved here because human review happens downstream on the normalised JSON output, not on each individual document edit.

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SUPERDOCS_API_KEY
uvicorn main:app --port 8010
```

## API

**`POST /normalize`**

```json
{
  "resumes": [
    {
      "id": "resume-001",
      "raw_text": "John Smith\njohn@example.com\n5 years Python...",
      "source": "pdf_upload"
    }
  ]
}
```

Returns:

```json
{
  "total": 1,
  "succeeded": 1,
  "failed": 0,
  "results": [
    {
      "id": "resume-001",
      "full_name": "John Smith",
      "email": "john@example.com",
      "phone": null,
      "location": null,
      "summary": "...",
      "years_of_experience": 5.0,
      "skills": ["Python", "FastAPI"],
      "education": [{"degree": "B.Sc.", "field": "Computer Science", "institution": "MIT", "year_completed": 2019}],
      "work_experience": [{"title": "Software Engineer", "company": "Acme", "start_year": 2019, "end_year": null, "summary": "..."}],
      "languages": ["English"],
      "normalisation_notes": null,
      "status": "normalised",
      "error": null
    }
  ]
}
```

On per-file failure, `status` is `"error"` and `error` describes the problem. `succeeded` + `failed` always sum to `total`.

## SuperDocs flow (per resume)

1. `POST /v1/chat/async` — send resume as `document_html`, normalisation instruction as `message`, `approval_mode: ask_every_time`
2. `GET /v1/jobs/{job_id}` — poll until `completed` or `awaiting_approval`
3. `POST /v1/chat/{session_id}/approve` — auto-approve proposed changes (human review is downstream)
4. `POST /v1/documents/export` — export the finished document as `txt`, parse as JSON

## Limits

- Max 50 resumes per batch
- 5-minute timeout per resume
- Resumes that cannot be parsed report `status: "error"` with a description
