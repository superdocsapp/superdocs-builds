# Role profile template

This specification is the source-controlled employee-readable profile structure. Every classified role uses the same schema.

## Header

- Role title
- Job family
- Career track
- Level
- Classification (`strong_fit` or `provisional`)

Provisional profiles must keep classification visible. Do not present them as finalized.

Misfits and unclassified provisional roles do **not** use this template. They use a review/misfit artifact instead.

## Body sections

Use these section ids in documents and in the dependency graph:

| Section id | Content |
| --- | --- |
| `purpose` | Role purpose |
| `responsibilities` | Responsibilities |
| `scope_decision_making` | Scope / decision making from the source job description |
| `core_competencies` | Family matrix competencies for this role |
| `level_expectations` | Canonical level-definition dimensions (depends on `level_id` + version) |
| `progression` | Next-level framing by label, without copying another level's wording |
| `evidence_note` | Source/evidence note |

## Surgical updates

When a canonical level definition changes, SuperDocs instructions must target `level_expectations` only. Do not tell SuperDocs to rewrite the profile.
