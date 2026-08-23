# Corpus labelling and review protocol

The corpus labels document scope, not a preferred model answer. Each instruction is paired with one or more acceptable scopes. A scope contains the chunk IDs that should change, the chunk IDs that must not change, after-state checks, and a short rationale.

## Primary labelling

1. Start from an unedited source document containing stable `data-chunk-id` attributes.
2. Write one instruction that belongs to exactly one required type: single sentence, one section, table row, or global rename.
3. Identify the smallest document units that must change to satisfy the instruction.
4. Mark every independent, unrelated unit as protected. Do not mark a structural parent as protected when changing its labelled child necessarily changes the parent's serialized HTML.
5. Add required and forbidden after-state fragments where a target can change without satisfying the requested value.
6. Record why the scope is correct without referring to observed SuperDocs output.

Labels are completed before any evaluation result is inspected. This prevents result-driven relabelling.

## Ambiguous instructions

If two careful readers can reasonably select different targets, the case is retained and marked with an `ambiguity_note`. Every defensible interpretation is represented as a separate `acceptable_scope`. The scorer evaluates all documented scopes and uses the lowest-loss match. It never silently invents a new acceptable interpretation after seeing an output.

`section-notice-ambiguous` is the corpus example: “Set the notice period to 45 calendar days” can reasonably target employee notice, employer notice, or both.

## Independent second review

The second reviewer must not be the primary labeler. For each case, the reviewer checks:

- instruction type and wording;
- expected and protected chunk IDs against the source document;
- required/forbidden after-state fragments;
- ambiguity decision and alternative scopes;
- rationale without viewing benchmark results.

The reviewer records a public display name, sets `review_status` to `approved` or `changes_requested`, and supplies adjudication notes in the pull-request review. Any disagreement is resolved before a full live run. A primary author must never fabricate the second reviewer.

The checked-in corpus intentionally remains `pending` until an actual independent reviewer signs it. The dashboard exposes this status rather than presenting unreviewed labels as final.

## Versioning

Corpus changes that affect labels require a new report. Result JSON records the exact case IDs, approach, per-unit diffs, and run mode so published numbers remain auditable.
