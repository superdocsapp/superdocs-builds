# PROGRESS.md — the assumption log

Every entry here is a place where the build had to decide something the brief
did not settle, and the decision was made by judgement rather than by looking it
up. The question, the call, the reasoning. Facts I looked up and confirmed are
not in here; they are in the code, next to what depends on them.

---

## 2026-08-15 — `SUPERDOCS_API_BASE` vs `SUPERDOCS_BASE_URL`

**Question.** `.env.example` and `preflight.py` were written before the client
was copied across, and they name the SuperDocs base URL `SUPERDOCS_API_BASE`.
The client copied from the sibling build reads `SUPERDOCS_BASE_URL`. One of them
has to move.

**Call.** The client wins; `.env.example` and `preflight.py` are renamed to
`SUPERDOCS_BASE_URL`.

**Reasoning.** The client is the file that was verified against the live service
and the one another integrator is most likely to lift. Renaming the variable in
the diagnostic costs one line; renaming it in the client means the copied file
no longer matches its origin, which is exactly the drift this whole project is
about. Both files also keep it optional — empty means the client's own default,
`https://api.superdocs.app`.

## 2026-08-15 — copying `superdocs.py` rather than importing it

**Question.** The sibling build in this same repository has a live-verified
SuperDocs client. Import it, vendor it, or rewrite it?

**Call.** Copy the file, with a provenance paragraph at the top of its
docstring.

**Reasoning.** `CONTRIBUTING.md` says to build inside my own folder only, so an
import across project folders is out; the two projects are also not a package
that could carry a shared dependency. Rewriting it would throw away a set of
API behaviours that cost real time to establish — the double-parse of
`proposed_change_batch`, the approval default, the long-poll tolerance — and
would read as if they had been discovered twice. The provenance paragraph is
what keeps the copy honest.

## 2026-08-15 — three commitments taken from the task document, designed in rather than retrofitted

**Question.** The task document's "what done looks like, for any build in this
round" list is written for the shared Task 1 system. How much of it applies to a
build submitted under Task 2?

**Call.** Three of them are treated as binding here and are designed in from
Stage 2 rather than bolted on at Stage 12:

1. **Configuration over code.** "A new rule, court, client, or format should be
   a data change, not a rewrite." So the vertical checks are a rules *file*
   read by a small generic engine, not one Python function per rule. Adding
   "check the PagerDuty escalation policy name" must be a YAML entry.
2. **A run knows what it cost.** Every sweep reports operations spent and
   wall-clock per stage, and the zero-spend case reports a literal zero rather
   than staying silent.
3. **Concurrency does not corrupt state.** Two sweeps at once stay two sweeps.
   That is a property of the register, so it belongs in the register's design
   (WAL, a transaction per finding, `claim_id` as the idempotency key) and not
   in a lock bolted around the CLI later.

**Reasoning.** All three are cheap now and expensive later. The rules-as-data
one especially: retrofitting it means rewriting every check, and the difference
between a linter and a product is whether a new rule needs a programmer.

## 2026-08-15 — one finding per dead service, not one per sentence

**Question.** Page 1005 in the corpus describes `notify-gateway`, a service that
exists in no manifest and no catalog entry. Every claim on it — threshold,
namespace, replica count, escalation target — is unsupported. Does each become a
`contradicts` finding?

**Call.** No. A page whose subject resolves to nothing produces exactly one
finding, `orphan_runbook`, and its remaining claims are recorded `unverifiable`.

**Reasoning.** Five findings for one dead service is five review-queue entries
with one decision behind them, and the decision is not "fix this sentence" — it
is "archive the page, or name the successor". Getting that wrong is how a tool
in this class gets uninstalled in week two. The `unverifiable` verdict is what
makes this honest rather than a suppression: the claims are still recorded, and
still counted, as things nobody checked.

## 2026-08-15 — angle brackets mean placeholder

**Question.** `kubectl -n <your-namespace> top pods` appears in the corpus, as
it does in every real runbook. Is `<your-namespace>` a namespace that does not
exist?

**Call.** A claim containing an angle-bracketed token is `unverifiable`, never
`contradicts`.

**Reasoning.** This is risk 3 from the brief and it is not a small one: a
checker without this convention fires on nearly every command block in a real
estate, and the false-positive rate eats the product before anyone gets to the
findings that are real. The convention is stated in `expected.yaml` so it is
part of the measured contract rather than an undocumented quirk of the
implementation.

## 2026-08-15 — dead links are checked against declared dashboards, not by fetching them

**Question.** How is "the dashboard link is dead" established?

**Call.** By resolving the link's uid against dashboards declared in the infra
repo. Nothing is fetched.

**Reasoning.** Fetching would be more thorough and much less honest: it makes
the checker's output depend on network reachability, VPN state and whoever's
Grafana is up at the time, and it turns a deterministic offline stage into a
flaky one. The limitation — git-declared config, not live cloud state — is
stated in the README rather than papered over. A link to a dashboard nobody
declared is worth reporting on its own terms.

## 2026-08-15 — `fixtures/` before any checking code

**Question.** Stage order: build the readers against real-ish files, or build
the corpus first?

**Call.** Corpus first, and `expected.yaml` written before the checker exists.

**Reasoning.** Precision and recall are only meaningful against a key that was
written without knowing what the checker would find. Writing the corpus after
the checker means writing fixtures the checker already passes, which measures
nothing. This is the one place where doing it in the awkward order buys
something real.
