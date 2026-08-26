# Template Filler from a Record

**Open list pick — Band S1**  
Fills document templates from JSON records using SuperDocs. Built for the SuperDocs engineering task.

## What it does

- Accepts a template (any text with `{placeholders}`) + a JSON record
- Fills every placeholder from the record
- Fields the record doesn't answer become `[MISSING: field_name]` — never invented
- Conditional sections (`[SECTION: label]...[/SECTION: label]`) resolve based on configurable rules
- Every fill waits in SuperDocs HITL review before being returned

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # add SUPERDOCS_API_KEY
uvicorn main:app --port 8012
```

## API

**`POST /fill`**

```json
{
  "document_title": "Offer Letter",
  "template_text": "Dear {candidate_name},\n\nYour role: {role_title}...",
  "record": {
    "candidate_name": "Priya Sharma",
    "role_title": "Senior Engineer"
  },
  "gap_marker_style": "[MISSING: {field}]"
}
```

Response:

```json
{
  "document_title": "Offer Letter",
  "filled_text": "Dear Priya Sharma,\n\nYour role: Senior Engineer...",
  "gaps": [],
  "session_id": "sess_abc123",
  "status": "approved"
}
```

See `example_request.json` for a full example with conditional sections.

**`POST /fill/batch`** — up to 20 templates at once.

## What strong looks like

Ten different records produce ten documents whose content comes from the record and whose structure comes from the template — never swapped. Missing fields are reported honestly, not papered over.
