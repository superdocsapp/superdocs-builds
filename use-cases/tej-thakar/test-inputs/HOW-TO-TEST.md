# How to test Task 2 builds

## Prerequisites

```bash
# Each build: set SUPERDOCS_API_KEY and SUPERDOCS_BASE_URL in its .env file
# then start all four services:
cd resume-normaliser  && uvicorn main:app --port 8010 &
cd claims-generator   && uvicorn main:app --port 8011 &
cd template-filler    && uvicorn main:app --port 8012 &
cd house-style-enforcer && uvicorn main:app --port 8013 &
```

---

## 1 — Resume Normaliser (port 8010)

Test input: `test-inputs/resume-normaliser-test.json`

Three real-structure resumes (Aiko Kobayashi — Go/distributed systems, Kwame Osei — frontend/DX,
Valentina Martinez — ML/NLP). Each is plain text as it would arrive from a PDF parse.

```bash
curl -s -X POST http://localhost:8010/normalize \
  -H "Content-Type: application/json" \
  -d @test-inputs/resume-normaliser-test.json | jq .
```

Expected response shape:
```json
{
  "total": 3,
  "succeeded": 3,
  "failed": 0,
  "results": [
    {
      "id": "resume-001-kobayashi",
      "full_name": "Aiko Kobayashi",
      "email": "aiko.kobayashi@gmail.com",
      "skills": ["Go", "Python", ...],
      "status": "normalised",
      ...
    },
    ...
  ]
}
```

What to check:
- `succeeded` = 3, `failed` = 0
- Each result has `status: "normalised"` and populated structured fields
- `years_of_experience` is a number, not null
- `skills` and `work_experience` are lists

---

## 2 — Claims Generator (port 8011)

Test input: `test-inputs/claims-generator-test.json`

Three fictional test cases: partial approval (hail damage), denial (flood exclusion),
information request (missing auto claim docs).

### Step 1: generate (call /generate for one case)

```bash
# Partial approval case
curl -s -X POST http://localhost:8011/generate \
  -H "Content-Type: application/json" \
  -d '{
    "claimant": {
      "full_name": "Priya Sharma",
      "address": "47 Ferndale Avenue, Austin, TX 78701",
      "email": "priya.sharma.test@example.com"
    },
    "policy": {
      "policy_number": "HO-2026-TX-009142",
      "coverage_limit": 80000,
      "deductible": 6000,
      "coverage_type": "homeowner"
    },
    "claim": {
      "claim_number": "CLM-2026-0314",
      "incident_date": "2026-06-28",
      "incident_type": "hail and wind damage — roof and siding",
      "claimed_amount": 72000,
      "adjuster_estimate": 58500,
      "adjuster_notes": "Claimant included pre-existing soffit deterioration not caused by the June storm. Roof replacement approved at 80% replacement cost; siding agreed at full replacement cost."
    },
    "letter_type": "partial_approval",
    "company_name": "MapleCrest Insurance Group"
  }' | jq .
```

Expected: `"status": "pending_hitl"` with a `session_id`.

### Step 2: approve (human review gate)

```bash
SESSION_ID="<session_id from above>"
curl -s -X POST "http://localhost:8011/approve/$SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{"approved": true}' | jq .
```

Expected: `"status": "approved"` with `letter_html` and `letter_text` populated.

---

## 3 — House-Style Enforcer (port 8013)

Quick self-contained test (style guide + document inline):

```bash
curl -s -X POST http://localhost:8013/audit \
  -H "Content-Type: application/json" \
  -d '{
    "style_guide_text": "1. Always use \"we\" not \"I\" when writing on behalf of the company.\n2. Product names must be capitalised exactly as trademarked: MapleCrest, not Maplecrest or maple crest.\n3. Headings must be sentence case, not title case.\n4. Avoid passive voice in action sections.",
    "document_text": "Dear Mr. Jones,\n\nI am writing to inform you that maplecrest Insurance have reviewed your claim.\n\nThe Following Documents Are Required:\n- Policy Certificate\n- Photos of Damage\n\nPlease Be Advised that failure to provide these documents may result in your claim being delayed.",
    "document_title": "Test letter — style audit"
  }' | jq .
```

Expected: `"clean": false` with at least 3–4 violations (capitalisation, pronoun, heading case, passive voice), each with a `style_guide_citation`.

---

## 4 — Template Filler (port 8012)

### Step 1: fill

```bash
curl -s -X POST http://localhost:8012/fill \
  -H "Content-Type: application/json" \
  -d '{
    "template_text": "Dear {{claimant_name}},\n\nThank you for your claim {{claim_number}} submitted on {{incident_date}}.\n\nYour policy ({{policy_number}}) covers {{coverage_type}} with a deductible of ${{deductible}}.\n\nThe next step is {{next_step}}.\n\nSincerely,\n{{adjuster_name}}\n{{company_name}}",
    "record": {
      "claimant_name": "Priya Sharma",
      "claim_number": "CLM-2026-0314",
      "incident_date": "2026-06-28",
      "policy_number": "HO-2026-TX-009142",
      "coverage_type": "homeowner",
      "deductible": "6,000",
      "company_name": "MapleCrest Insurance Group"
    },
    "document_title": "Acknowledgement letter — Priya Sharma"
  }' | jq .
```

Expected: `"status": "pending_hitl"` with a `session_id`.
Note `next_step` and `adjuster_name` are not in the record, so they become `[MISSING: next_step]` etc.

### Step 2: approve

```bash
SESSION_ID="<session_id from above>"
curl -s -X POST "http://localhost:8012/approve/$SESSION_ID" \
  -H "Content-Type: application/json" \
  -d '{"approved": true}' | jq .
```

Expected: `"status": "approved"`, `filled_text` with real values and `[MISSING: ...]` markers for the two absent fields, `gaps: ["next_step", "adjuster_name"]`.
