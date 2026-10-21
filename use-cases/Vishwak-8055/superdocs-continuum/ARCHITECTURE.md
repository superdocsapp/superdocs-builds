# Architecture

## Pipeline

```
DOCUMENTS + OBJECTS + EDGES              (src/data.js — static fixture data)
    |
buildWorld(paymentTermDays)              -> canonicalWorld or candidateWorld:
    |                                        every document rendered for one
    |                                        specific Payment Term value
    v
computeConsequences(startId)             -> what depends on the changed
    |                                        object, tiered by edge class
    v
forecastContradictions(old, proposed)    -> pre-existing conflicts
    |                                        (resolved / still open) versus
    |                                        genuinely new violations
    v
diffWorlds(canonical, candidate,         -> text diff + semantic diff
           edges, objects, forecast)         between two real worlds
    v
scenario state machine                   -> DRAFT..REVIEW..APPROVED..
    |                                        APPLYING..VERIFYING
    v
runVerification(canonical, candidate,    -> six checks against the actual
                diff, forecast, ...)         candidate world
    v
commitWorld(version, verification,       -> COMMITTED (new canonical world
            candidateWorld)                  + version) or nothing to commit
```

## World model

A **world** is the output of `buildWorld(docText, objects, paymentTermDays)`:
every document in the corpus, fully rendered for that specific term value,
plus a map of every object's current value. It is the single rendering
path in the system. There is exactly one **canonical world** at a time
(driven by the UI's `canonicalValue`), and proposing a change builds an
independent **candidate world** alongside it — building a candidate never
touches the canonical world's object, and the canonical world is re-derived
fresh (via `useMemo`) only when a commit actually changes `canonicalValue`.
`tests/engine.test.js` asserts this directly: building several candidate
worlds in a row leaves an already-built baseline's own fields and rendered
text unchanged.

Four of the six documents (Sales Terms, Renewal Policy, Pricing Policy,
Enterprise Terms Addendum) contain no `{TERM}`/`{NET}` placeholder tied to
the Payment Term, so they render byte-identically regardless of the
proposed value — this is asserted directly in `tests/engine.test.js` and
is what the "unchanged region" verification check below relies on.

`resolveEvidence(world, objects, objectId)` checks a semantic object's
evidence template against the *actual rendered text* of its source section
in a given world. Baseline evidence is always resolved against the
baseline world and candidate evidence against the candidate world — never
mixed — because every call site passes the specific world it means; there
is no function that resolves evidence without one.

## Consequence engine

`computeConsequences` runs a breadth-first traversal from the changed
object, but only across edges classed `structural`, `strong`, or `weak` —
edges classed `conflict` (`CONTRADICTS`, `CONSTRAINED_BY`) are excluded
from impact traversal entirely and handled by the forecast step instead,
because a relationship of tension is not a downstream effect. A node's
tier is its hop distance (1 = direct, 2 = indirect, 3+ = potential),
*capped* at "potential" if reaching it required crossing a `weak`
(REFERENCES-only) edge anywhere along the path. Parent pointers are kept
during traversal so `explain(id)` reconstructs the actual edge-by-edge path
from source to any affected node — every step in that chain corresponds to
a real edge, which `tests/engine.test.js` checks directly.

## Contradiction forecast

Two distinct kinds of conflict are modeled:

- **CONTRADICTS** — an equality clash against another stated term (the
  Sales Terms 45-day default). Resolved if the proposed value matches the
  other side's value exactly; otherwise still open. Resolving an existing
  conflict is never reported as a new violation.
- **CONSTRAINED_BY** — a cap a value must respect (the Enterprise Terms
  Addendum's 90-day ceiling). "Introduced" means the *current* value
  satisfies the constraint but the *proposed* value would not. The
  boundary itself does not violate it: proposing exactly 90 passes, 91 or
  above does not — both cases are tested directly.

## Diff

`diffWorlds(canonical, candidate, edges, objects, forecast)` compares two
independently rendered worlds section by section for text changes (guarded
against a document missing from either side, which is reported rather than
thrown), compares object values for semantic changes, and — when a
forecast is supplied — folds `CONFLICT_RESOLVED` and `CONFLICT_CREATED`
entries into the same semantic-change list, so the UI renders one list
from engine output instead of merging two structures itself. It also
returns `changedDocIds` and `unchangedDocIds`, which verification uses
directly.

## Scenario state machine

```
DRAFT -> ANALYZING -> SIMULATED -> REVIEW -> APPROVED -> APPLYING -> VERIFYING -> COMMITTED
  |  (from DRAFT or REVIEW)                                    |  (from APPLYING or VERIFYING)
REJECTED                                                  FAILED -> ROLLED_BACK
```

`nextState(current, requested)` is the only way to move between states —
it looks `current` up in a transition whitelist and throws
`IllegalTransitionError` if `requested` isn't allowed, so `DRAFT ->
COMMITTED` is structurally impossible. A scenario rejected at `REVIEW`
never reaches `APPROVED` or `COMMITTED` by construction — there is no
verification or commit call anywhere in that path.

## Verification

`runVerification(canonical, candidate, diff, forecast, edges, objects,
docMeta, requiredSections)` checks the actual candidate world, the actual
edge list, and the actual diff between the two worlds:

1. **structure** — every known document exists in the candidate world with
   at least one section.
2. **anchors** — every object's evidence template resolves against the
   candidate world's rendered text.
3. **sections** — the documents a change touches actually contain the
   section IDs they're supposed to have.
4. **no new conflicts** — the forecast's `introduced` list is empty.
5. **graph integrity** — every edge's endpoints exist among known document
   and object IDs.
6. **unchanged regions preserved** — every document *outside* the change
   (per `diff.unchangedDocIds`) is byte-identical between canonical and
   candidate. This is what "change what must change, leave everything else
   alone" actually means as a checked condition rather than a slogan.

A test constructs a candidate world with a document deleted and confirms
verification genuinely fails rather than throwing or silently passing.

## Commit

`commitWorld(canonicalVersion, verification, candidateWorld)` is a pure
function: if verification passed in full, it returns the candidate world
and an incremented version to become canonical; otherwise it returns
`{ committed: false, world: null, version: canonicalVersion }` — the
version explicitly unchanged and no world to commit. The caller (the UI's
`approve()`) only ever calls `setCanonicalValue`/`setVersion` inside the
`committed: true` branch, so a failed verification can't leave a partial
change: either both update together or neither does.

This is a single in-memory object swap, not database transaction
atomicity, and the UI describes it that way (the candidate world "replaces
canonical state in a single update") rather than claiming a stronger
guarantee than a client-side implementation provides.

## Health score

Labeled in the UI as a heuristic indicator, not a validated metric. All
five component dimensions are now computed from the actual corpus rather
than fixed: evidence coverage and provenance coverage come from
`resolveEvidence`/section-reference checks, structural integrity from the
same required-sections logic verification uses, dependency completeness
from whether each `Dependency`-typed object actually has a `DEPENDS_ON` or
`DERIVED_FROM` edge, and consistency from the real conflict count. A test
confirms removing a document from the world measurably lowers the score.
The entity count shown alongside it comes from a real `ENTITIES` array in
`src/data.js`.

## Build validation

`node --check` confirms plain JS modules parse but does not understand
JSX. `build/validate-jsx.js` parses `src/ui.jsx` and the assembled
`dist/document_os.jsx` with an actual JSX-capable parser and fails the
build on a real syntax error — `npm run check` runs this alongside
rebuilding the artifact, so "the build passed" is backed by something that
actually reads the JSX.
