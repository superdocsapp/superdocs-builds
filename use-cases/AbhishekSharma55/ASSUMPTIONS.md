# Assumptions and decisions, logged as they were made

The brief says a logged assumption counts in your favour. These are mine,
dated, with the reasoning. Where an assumption was later proved or disproved
by the live API, that is recorded too.

---

## 2026-08-07 — A1. Agent self-signup, free tier, 500 operations

Signed up with `POST /v1/agents/signup`. The account is a **free** tier account
with **500 operations per month**, not the 10,000 that the `BUILDER26` promo
grants on a human account.

**Consequence, and it shapes everything below:** every loop in this repo needs a
budget, a small-sample mode and a stopping rule from the first commit. That is
implemented in `superdocs_kit/budget.py` and it is not decoration — the 52-week
run and its control arm together would exhaust a careless budget.

**Assumption:** measuring cost in *billed operations* (`usage.ops_charged`,
which the server returns on every chat response) is a more honest unit than
tokens or wall-clock, because it is the unit the customer is actually charged
in and it does not depend on my model-tier choices. Time is recorded alongside
it, so a reader who cares about latency has the raw numbers too.

## 2026-08-07 — A2. Both builds share one client layer

`superdocs_kit/` sits under my username folder and both project folders import
it. CONTRIBUTING says build inside your own folder; a shared library inside
that folder is still inside it. The alternative — copy-pasting a client into
two projects — would have made the bug-fix in `changes.py` need fixing twice.

## 2026-08-07 — A3. "Edited, never regenerated" is measured against a real control arm

A cost claim with no control is a marketing number. So the measurement runs the
*same weekly inputs* through two arms:

- **Arm A (edit):** one document, one targeted-edit operation per week.
- **Arm B (regenerate):** the same content, but each week the whole digest is
  produced afresh, which is what a team does today when they copy last week's
  doc and rewrite it.

Both arms are billed by the same server meter. Method is written down before
the numbers, in `weekly-digest/MEASUREMENT.md`.

## 2026-08-07 — A4. Simulated weeks, real API calls

The 52 weeks of production input are **synthetic** (a fictional game studio,
per the brief's "synthetic or public documents only"). The *edits* are real:
52 real operations against the live API on one real document. Simulating the
calendar is not simulating the work.

## 2026-08-07 — A5. Domain: game production

Task 1 (separate private repo) uses a game-production corpus and assigned
build #2 is a game design document editor. Making build #1's digest a **game
studio's weekly production digest** means one fictional universe — *Nebula
Drift* by Vantage Nine Studios — carries all of it, and the demo tells one
story instead of three.

## 2026-08-07 — A6. Verification does not trust the API's own summary

`document_changes.changes_summary` says things like "1 section edited, rest
untouched". That is the system under test grading its own homework. Every
"only the intended section changed" claim in this repo is re-derived from the
document bytes by `superdocs_kit/docdiff.py`, independently. Where the two
disagree, the bytes win and it goes in `bugs.md`.

## 2026-08-07 — A7. A key leaked into a test fixture, was caught, and the history was rewritten

Recording this because the alternative is pretending it did not happen.

Writing the redaction tests, I used the **live API key** as one of the
"credential-shaped strings that must be redacted" fixtures. It was committed in
`tests/test_budget_and_secrets.py`, in four local commits.

Caught by running the pre-PR check in `PR-DRAFT.md` (`git log -p --all | grep -E
'sk_[a-z0-9]{8}'`) rather than by noticing at the time — which is the argument
for having that check written down as a step instead of trusting a habit.

Fixed: the fixture is now an obviously fake constant, the four commits were
rewritten with `git filter-branch`, the `refs/original` backups and the stash
were deleted, the reflog expired and the objects pruned. Verified with
`git cat-file --batch-all-objects --batch | grep` — **zero occurrences in any
git object.** Nothing had been pushed, so no remote ever saw it.

**Still outstanding, and it is Abhishek's call because it is his account:**
rotate the key anyway. A secret that touched a file on disk should be treated as
exposed even when the exposure was local.

```bash
# list, create a replacement, then revoke the old one
curl -s https://api.superdocs.app/v1/users/me/api-keys -H "Authorization: Bearer $KEY"
curl -s -X POST https://api.superdocs.app/v1/users/me/api-keys -H "Authorization: Bearer $KEY" \
     -H 'Content-Type: application/json' -d '{"name":"round-2-builder"}'
curl -s -X DELETE https://api.superdocs.app/v1/users/me/api-keys/<old_key_id> -H "Authorization: Bearer $NEW"
```

The lesson that went back into the code: `superdocs_kit/secrets.py` redacts
anything key-shaped before it can reach a fixture, and there is a test asserting
it — but neither helps against a key a human types into a source file. The only
defence there is the grep, so it is now step 1 of the PR checklist.

## 2026-08-07 — A8. Each GDD document gets its own session

SuperDocs' multi-document session returns a one-entry roster with every document
carrying `document_id: "doc_primary"`, non-deterministically (bugs.md B10,
`repro/B10-multidoc-roster.sh`). Since `/v1/chat`'s `document_id` is how you
target one document, and every document has the same one, targeted
cross-document editing has nowhere to land.

**Assumption:** the durable document id is the real identity and the session is
just a conversation handle. So build #2 gives each document its own session and
holds the link graph itself (`corpus.LINKS`, as data).

**What it costs, and I would say this before being asked:** the model never sees
two documents in one turn, so a cross-document request is decomposed by my code
rather than reasoned about by the model. If B10 were fixed I would use the real
multi-document session.

## 2026-08-07 — A9. The factual sections are handed over as literal HTML

Decided on evidence, and it is the biggest single change to the design.

The weekly instruction originally *described* the target — "replace all bullets
with exactly these four". Over seven live weeks that was read as **append** often
enough to matter: week 7 came back holding the five old bullets plus the four new
ones. Three rewordings reduced the rate without removing it. A severity cell came
back reading `Medium / Low` — both values at once.

So the three factual sections are now built as exact HTML by `document.py` and
spliced in. The model is not asked to author, re-type or reason about a fact.

**Why this is a narrowing and not a retreat:** it is the build's thesis at its
purest — facts transported, prose generated. The model still writes every archive
summary and every quarterly rollup *from what the document says*, which is the
part that genuinely needs a model and cannot be precomputed. And because the
alternating row shading is now generated rather than hoped for, formatting
preservation stops depending on the model noticing.

**The honest cost:** less of the document's content passes through the model, so
this build demonstrates *surgical editing* more than it demonstrates *authoring*.
Build #2 is where authoring is demonstrated, and there the instructions are prose
and the model does write the words.

## 2026-08-07 — A10. Escalate the model tier on failure rather than paying for it every week

When the instruction was ambiguous, the default tier dropped four of five steps
and `pro`/`deep` fixed it — at ~195 s a week against ~43 s. After A9 removed the
ambiguity, the **default tier passed the same week that had failed four times**,
4.5x faster.

**Assumption at the time:** the right place for the expensive model is the repair
path, not every turn. Attempt 1 on `core`/`balanced`, escalating to `pro`/`deep`.

**Disproved, and the code says so.** Over weeks 4–7 the default tier failed
first-attempt verification roughly 60% of the time, on the same checks. One
passing week was not evidence (`bugs.md` M4). Attempt 1 is back on `pro`/`deep`
in `runner.py` and in both READMEs. Tier does not change what SuperDocs bills, so
all of this was latency, never money — and both arms of the measurement use the
same policy, including the control arm, so the comparison stays symmetric.

**The general lesson, and the one worth carrying:** when a model gets something
wrong, look for the ambiguity before reaching for a bigger model. It was the
right first move — the literal-HTML change is what made the *content* correct and
it stayed — it just did not remove the need for the stronger model.

## 2026-08-08 — A11. A verification pass by a second pair of eyes, and what it changed

The brief recommends letting someone who did not write the code check it. Doing
that against this repo found three things the author's own checks had passed,
and they are worth logging because two of them were checks, not code:

1. **`bugs.md` M5** — the archive parser skipped rows it could not read, so a
   duplicated archive row passed an invariant named *"covers every past week
   exactly once"*. Fixed with a fourteenth invariant plus an instruction that
   names the label format. Weeks that had needed a two-turn repair every time
   now pass first attempt at one operation each.
2. **`bugs.md` M6** — the cross-document check treated added content as never
   unintended, so *"only the Concept art section changed"* passed a turn that
   appended a **second** Concept art section (now `bugs.md` B15).
3. **Counts in prose** — invariants, tests and bug totals had drifted apart from
   the code. Every number in these documents is now derived from something on
   disk, and the ones that could not be reproduced were removed rather than
   softened.

**Assumption going forward:** any number in a README is a claim, and a claim
needs a command that reproduces it. Where this repo states a number, the command
that produces it is next to it.
