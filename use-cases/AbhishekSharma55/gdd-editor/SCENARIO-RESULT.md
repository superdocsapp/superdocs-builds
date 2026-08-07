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
| 5 | the GDD gained the section 'Traversal - Grapple Rework' | **FAIL** |
| 6 | ACT 2: mechanics, narrative and art-bible are byte-identical | PASS |
| 7 | ACT 2: nothing else in the GDD moved | PASS |
| 8 | Mechanics now says the cooldown is 5 s | PASS |
| 9 | the GDD's Traversal prose now says 5 s and no longer says 8 s | PASS |
| 10 | ACT 3: ONLY the Grapple section changed in Mechanics | PASS |
| 11 | ACT 3: ONLY the Traversal section changed in the GDD | PASS |
| 12 | ACT 3: narrative, art-bible and the new sub-document are byte-identical | PASS |
| 13 | the other mechanics' numbers are unchanged | PASS |
| 14 | both concept plates are embedded in the Art Bible | PASS |
| 15 | embedding images changed nothing but the Concept art section | PASS |
| 16 | every document exports to .docx | PASS |
| 17 | every document exports to Markdown | PASS |

**16/17 passed** in 5 billable operations and 277s.

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
        "sections_changed": [
          "40120a2e-0f5e-4087-a3ac-64db214e98a1",
          "6e39411d-af8e-403b-9706-7a3407ca5968"
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
          "c9c72155-affd-416f-8b0b-3db6528af4a7"
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
          "06f09bdd-ff90-446c-b44f-b75b5e2b802d"
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
          "6a2e5064-11b6-43fb-b6d7-cdfc4d284825"
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
