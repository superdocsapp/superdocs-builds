# Patent-Drafting Assistant

This use case maintains a set of numbered, cross-referencing patent claims. Claims dependency
("the widget of claim 1...") is derived deterministically from claim text, never guessed. Amending or
deleting one claim computes every other claim that transitively depends on it and surfaces that list on
the proposal and in the permanent revision history — it is never silently left inconsistent. Amending a
claim never rewrites a dependent claim's text automatically; the assistant flags the dependents for
attorney judgment instead of guessing new wording on their behalf.

This produces a **draft for attorney review, not a filed or certified document**.

## Workflow

1. Draft an initial claim set (`patent_claims.build_claim_set` / `patent_from_payload`), one claim per
   number, contiguous, referencing only earlier or later claims that exist.
2. Submit a plan naming exactly one `claim_number` and an `action` (`amend` with `new_text`, or `delete`).
3. The manager computes the proposed claim set, the diff against the current one, and every claim that
   transitively depends on the changed claim.
   - An amendment to an independent claim used elsewhere is `awaiting_review` with `flagged_dependents`
     listing every claim that references it, directly or transitively.
   - A delete of a claim that others still depend on is refused outright (`blocked`) rather than silently
     repointing those references.
4. A reviewer approves or rejects the proposal. Rejection leaves the claim set byte-identical; approval
   creates revision `N+1` and appends an entry to `revision_history` that records the flagged dependents
   alongside the change, so the record of what was surfaced is permanent, not just a UI moment.
5. Export requires an approved proposal that still describes the current revision (a second proposal
   approved after the patent has already moved on is refused, not silently applied to stale state).

## Run

No live key, model, database server, or external renderer is required.

```bash
cd use-cases/RSWDevian/patent-claim-drafting-assistant
python3 -m unittest discover -s tests -v
```

## Machine Interfaces

```bash
python3 -m patent_claims.server
```

REST routes: `POST /v1/builds/patent`, `GET /v1/patents/{patent_id}`,
`POST /v1/patents/{patent_id}/chat`, `GET /v1/proposals/{proposal_id}`,
`POST /v1/proposals/{proposal_id}/decision`, `POST /v1/patents/{patent_id}/export`.
The same lifecycle is available at `POST /mcp` with `patent_start`, `patent_get`, `patent_chat`,
`patent_review`, `patent_decide`, and `patent_export`.

## What Strong Looks Like, Demonstrated

Amending independent claim 1 of a three-claim fixture (claim 2 depends on claim 1, claim 3 depends on
claim 2) reports `flagged_dependents: [2, 3]` on the proposal, on approval, and in `revision_history` —
see `tests/test_patent_claims.py::test_amend_independent_claim_flags_transitive_dependents` and
`test_approving_amendment_creates_new_revision_and_records_flagged_dependents`. Deleting claim 1 of the
same fixture is refused with `claim(s) [2] depend on it directly`, not silently applied with claim 2 left
pointing at a claim that no longer exists.

## Local Export Artifacts

Local exports produce valid HTML, Open XML DOCX, and PDF bytes without third-party packages, matching the
sibling Task 2 builds in this repository. SQLite is the local persistence boundary; a hosted SuperDocs
export adapter and PostgreSQL are production concerns outside this fixture slice.

## Limitations

Claim numbering must be contiguous starting at 1, matching the common single-document-family case; a
production version would need continuation/divisional claim-number namespacing. Reference detection is a
deterministic `"claim(s) N[, and/through M]"` regex over claim text, not a full patent-claim grammar
parser — claims that reference a preceding claim using other phrasing will not be linked. This is a
drafting aid, not a legal opinion on claim validity, novelty, or scope.

Built as a voluntary open-list Task 2 use case, in addition to the assigned builds.
