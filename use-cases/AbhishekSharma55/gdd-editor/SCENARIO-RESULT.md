# Graded scenario - result

> *a reviewer asks for a new GDD section plus one linked sub-document,
> then requests a revision to one mechanic - and only the correct
> section changes across both documents.*

Regenerate with `gdd scenario --live`. Every row is re-derived from the
document bytes; none of it is taken from the API's own change summary.

| # | Check | Result |
|---|---|---|
| 1 | workspace seeded with the GDD and three linked sub-documents | PASS |
| 2 | the Grapple cooldown starts at 8 s in Mechanics | PASS |
| 3 | the GDD's Traversal section also says 8 s | PASS |
| 4 | the linked sub-document was authored | PASS |
| 5 | the GDD gained the section 'Traversal - Grapple Rework' | PASS |
| 6 | the new section contains only what was asked for (no invented table) | PASS |
| 7 | ACT 2: the only new document is the linked sub-document | PASS |
| 8 | ACT 2: mechanics, narrative and art-bible are byte-identical | PASS |
| 9 | ACT 2: nothing else in the GDD moved | PASS |
| 10 | Mechanics now says the cooldown is 5 s | PASS |
| 11 | the GDD's Traversal prose now says 5 s and no longer says 8 s | PASS |
| 12 | ACT 3: ONLY the Grapple section changed in Mechanics | PASS |
| 13 | ACT 3: ONLY the Traversal section changed in the GDD | PASS |
| 14 | ACT 3: narrative, art-bible and the new sub-document are byte-identical | PASS |
| 15 | the other mechanics' numbers are unchanged | PASS |
| 16 | the Art Bible has exactly one 'Concept art' section | PASS |
| 17 | both concept plates are embedded in the Art Bible | PASS |
| 18 | embedding images changed nothing but the Concept art section | PASS |
| 19 | every document exports to .docx | PASS |
| 20 | every document exports to Markdown | PASS |

**20/20 passed** in 6 billable operations and 542s.

## Per-document surgical check

For each act: which sections were allowed to change, which actually
changed, and how many sections came back byte-identical.

```json
{
  "act-2": {
    "documents": {
      "gdd": {
        "expected": [
          "Linked sub-documents",
          "Traversal - Grapple Rework"
        ],
        "new_sections_allowed": true,
        "sections_changed": [
          "05c3fbbf-2cc7-4510-bd49-35cf3dc82f85",
          "18b90591-cc3e-4764-84c5-a529c10c7618"
        ],
        "unintended": [],
        "byte_identical_sections": 22,
        "ok": true
      },
      "mechanics": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "narrative": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "art-bible": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "grapple-rework": {
        "expected": "created by this act",
        "created": true,
        "ok": true
      }
    },
    "ok": true
  },
  "act-3": {
    "documents": {
      "gdd": {
        "expected": [
          "Traversal"
        ],
        "new_sections_allowed": false,
        "sections_changed": [
          "d89ecf30-9600-4981-8c99-e67073aec372"
        ],
        "unintended": [],
        "byte_identical_sections": 23,
        "ok": true
      },
      "mechanics": {
        "expected": [
          "Grapple"
        ],
        "new_sections_allowed": false,
        "sections_changed": [
          "214b47df-2cd4-4cfa-9e2c-8df39c391577"
        ],
        "unintended": [],
        "byte_identical_sections": 13,
        "ok": true
      },
      "narrative": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "art-bible": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "grapple-rework": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      }
    },
    "ok": true
  },
  "images": {
    "documents": {
      "gdd": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "mechanics": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "narrative": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      },
      "art-bible": {
        "expected": [
          "Concept art"
        ],
        "new_sections_allowed": false,
        "sections_changed": [
          "07dfa5f7-79cb-4737-b248-830b86536a0a"
        ],
        "unintended": [],
        "byte_identical_sections": 8,
        "ok": true
      },
      "grapple-rework": {
        "expected": "byte-identical",
        "byte_identical": true,
        "ok": true
      }
    },
    "ok": true
  }
}
```
