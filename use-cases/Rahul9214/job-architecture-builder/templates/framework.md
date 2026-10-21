# Job architecture framework template

This specification is the source-controlled structure for the canonical framework document. A DOCX SuperDocs template can wrap the same sections later.

## Required sections

1. Purpose
2. Principles
3. Career tracks
4. Canonical levels — IC1, IC2, IC3, IC4, IC5, M1, M2, M3
5. Job families
6. Competency matrices by family
7. Role mappings
8. Provisional roles
9. Misfits

## Canonical level block

Each level must include a stable `level_id`, a `version`, and these dimensions:

- scope
- autonomy / decision authority
- complexity
- impact
- leadership
- people-management expectations (required for M1–M3; explicit "none" for IC)

Do not identify a level only by prose. Profiles depend on `level_id` + `version`.

## Competency matrix block

Each family matrix lists constrained competencies:

- competency id
- family id
- name
- description
- expectations by level where the family occupies that level

If classified role evidence is thin, keep the matrix generic and state the limitation.

## Generation rule

Populate this template from `FrameworkDocument` objects. Do not reconstruct the framework by parsing free prose.
