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
