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
| 7 | ACT 2: mechanics, narrative and art-bible are byte-identical | PASS |
| 8 | ACT 2: nothing else in the GDD moved | PASS |
| 9 | Mechanics now says the cooldown is 5 s | PASS |
| 10 | the GDD's Traversal prose now says 5 s and no longer says 8 s | PASS |
| 11 | ACT 3: ONLY the Grapple section changed in Mechanics | PASS |
| 12 | ACT 3: ONLY the Traversal section changed in the GDD | PASS |
| 13 | ACT 3: narrative, art-bible and the new sub-document are byte-identical | PASS |
| 14 | the other mechanics' numbers are unchanged | PASS |
| 15 | both concept plates are embedded in the Art Bible | PASS |
| 16 | embedding images changed nothing but the Concept art section | PASS |
| 17 | every document exports to .docx | PASS |
| 18 | every document exports to Markdown | PASS |

**18/18 passed** in 6 billable operations and 368s.

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
          "Traversal - Grapple Rework",
          "Traversal"
        ],
        "sections_changed": [
          "133c58ab-7285-405d-92b9-d9912f673df3",
          "26724c8f-09f5-4d49-8361-5f9cba89f0e2"
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
        "expected": "byte-identical",
        "byte_identical": false,
        "ok": false
      }
    },
    "ok": false
  },
  "act-3": {
    "documents": {
      "gdd": {
        "expected": [
          "Traversal"
        ],
        "sections_changed": [
          "a611e8b5-3ee8-4319-8bda-dc9c71a12f99"
        ],
        "unintended": [],
        "byte_identical_sections": 23,
        "ok": true
      },
      "mechanics": {
        "expected": [
          "Grapple"
        ],
        "sections_changed": [
          "0f6479ac-83ab-4074-b3f1-7a7f0d7a3efa"
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
        "sections_changed": [
          "a1f16fef-a4fd-43ce-be29-e5b1215f8c5e"
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
