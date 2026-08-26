# House-Style Enforcer

**Open list pick — Band S2**  
Audits documents against a style guide using SuperDocs. Built for the SuperDocs engineering task.

## What it does

- Accepts the actual style guide as a document (PDF or text — not a hardcoded rules file)
- Audits any document against it in two lanes: **language** (terminology, banned phrasing, capitalisation) and **formatting** (heading levels, list style, table treatment)
- Every violation cites the exact style-guide passage it's based on — no invented rules
- Swapping in a different style guide changes the behaviour with zero code changes
- All output waits in SuperDocs HITL review before being returned

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # add SUPERDOCS_API_KEY
uvicorn main:app --port 8013
```

## API

**`POST /audit`**

```json
{
  "document_title": "Q3 Report Draft",
  "style_guide_text": "...(paste the style guide here)...",
  "document_text": "...(paste the document to audit here)...",
  "lanes": ["language", "formatting"]
}
```

Response:

```json
{
  "document_title": "Q3 Report Draft",
  "clean": false,
  "total_violations": 2,
  "language_violations": [
    {
      "lane": "language",
      "severity": "error",
      "location": "paragraph 2",
      "excerpt": "utilise the platform",
      "issue": "Style guide requires 'use' not 'utilise'",
      "style_guide_citation": "Prefer simple verbs: 'use' not 'utilise', 'start' not 'commence'.",
      "suggested_fix": "use the platform"
    }
  ],
  "formatting_violations": [],
  "status": "approved"
}
```

**`POST /audit/batch`** — up to 20 audits at once.

## What strong looks like

The style guide is read, not transcribed into hardcoded rules. Swapping in a different client's guide changes the behaviour with no code change. Citations point to real passages. Formatting fixes do not disturb content, and language fixes do not disturb formatting.
