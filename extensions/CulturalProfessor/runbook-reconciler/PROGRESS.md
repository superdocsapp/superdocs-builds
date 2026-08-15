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

## 2026-08-15 — what `rr check` reads when a `.env` is sitting there

**Question.** Stage 8 gave the commands a `page_source(config)` helper that
prefers Confluence when it is configured. That is obviously right for an
operator. It is not obviously right for `rr check` on a machine that has
credentials for an unrelated site, and it is definitely wrong for the test
suite: `Config.load()` reads the real `.env`, so the moment the helper landed,
`rr check` under pytest started making live HTTP calls and the suite went from
ten seconds to thirty-four.

**Call.** Three modes, in `RR_SOURCE`: `auto` (the default — Confluence when
all three of site, email and token are set, the corpus otherwise), `corpus`,
and `confluence`. `conftest.py` pins `corpus` for the whole suite in an autouse
session fixture, and `--corpus` is a flag on `check`, `sweep` and `review`.
Asking for `confluence` without the credentials is an error rather than a
silent fallback. Every command that reads pages now prints which source it read
before it prints what it found.

**Reasoning.** The failure this prevents is not a crash, it is a *plausible
wrong answer*: the live read returned seven contradictions and zero claims,
which looks like a working run and is actually a report about somebody else's
wiki. Anything that can silently change what a number is about has to say what
it is about, and a test suite whose behaviour depends on an untracked file is
not evidence of anything. `measure` deliberately does not consult the helper at
all — it is scored against the corpus's planted drift, so reading anything else
would produce a precision figure about the wrong estate.

## 2026-08-15 — `rr propose` prices the work before it does it

**Question.** `propose` is the only command that can be charged for. Should it
just run, the way `check` does?

**Call.** No. Run it and it prints the exact cost — one operation per page, the
pages named — and stops. `--yes` is what actually spends.

**Reasoning.** The estimate is exact rather than indicative, which is the whole
point: "this may incur charges" tells an operator nothing they can act on,
while "7 operations, one for each of these pages" is a number they can decide
about. It also makes the zero-spend property visible at the command line rather
than only in a test — a clean estate prints "nothing to propose" and there is
no path from there to a request.

## 2026-08-15 — rule 6 does not work the way the plan said it would

**Question.** The plan is specific about how the watcher avoids re-triggering on
its own writes: `read:user:confluence` is "load-bearing — it gives our own
accountId". Ignore the page version whose `version.authorId` is us. Does that
work?

**Call.** No, and the mechanism is now a version ledger in the register:
`apply.py` records the exact version number each of its PUTs produced, in the
same transaction that marks the finding applied, and the watcher asks
`register.wrote_version(page_id, version)`. `account_id()` is kept as a second
filter for the classic-token case and is never the only one.

**Reasoning.** Checked against the live site rather than assumed. The author id
is genuinely in the v2 page payload, so the idea was sound — but every route to
"who am I" is refused for a scoped API token:

    GET /wiki/api/v2/users/current   -> 401 Unauthorized; scope does not match
    GET /wiki/rest/api/user/current  -> 401 Unauthorized; scope does not match
    GET https://api.atlassian.com/me -> 401 Unauthorized

with `read:user:confluence` granted. `read:me` is an Atlassian *account* scope
rather than a product one and is not grantable to an API token at all.

The replacement is better evidence anyway, which is worth saying rather than
presenting it as a consolation. An author id would only establish that the
integration account made the edit — a colleague using the same service account
is indistinguishable from us. The version number establishes that this exact
byte-for-byte version is the one our own PUT returned. Unknown authorship is
treated as somebody else's edit throughout: the cost of being wrong that way is
one unnecessary sweep, which is free, and the cost of the other way is a
runbook changing with nobody told.

## 2026-08-15 — the CI action and the git hook ship as templates, not installed

**Question.** Stage 9 wants a CI action and a pre-commit hook. Both normally
live at a repository root — `.github/workflows/` and `.git/hooks/`.

**Call.** Both ship inside this project folder as files to copy: `ci/`
and `hooks/pre-commit`, each carrying its own install line.

**Reasoning.** `CONTRIBUTING.md` says to build inside my own folder and modify
nothing outside it. Beyond the rule, a workflow at the root of a repository full
of other people's submissions would run on every push to all of them, which is
precisely the kind of thing that rule exists to prevent. The hook is a template
for the same reason plus a better one: it belongs in the repository that holds
the infrastructure, which is not this one.

The hook always exits zero, and that is the whole design rather than a caveat.
A blocking hook that costs thirty seconds gets `--no-verify` the first time and
uninstalled the second, and then the tool is absent from the one moment it had
the engineer's attention. It also prints nothing at all unless there is drift.

## 2026-08-15 — the readiness table reported a service as verified while it was drifting

**Question.** How does a finding get attributed to a service in the readiness
table? The obvious answer is by subject: the register knows each claim's
subject, so join on the service's name.

**Call.** By subject *and* by page. A finding also belongs to a service when it
sits on a page that service's claims are on.

**Reasoning.** The subject-only join was written, looked right, and was wrong in
the worst available direction. `payments-api`'s runbook carries a threshold
contradiction filed under `alert:PaymentsApiHighLatency:threshold` — a subject
that contains the service's name nowhere — so the first version of the table
printed `payments-api · 8 verified · 0 drift · verified` while page 1001 held a
live contradiction the checker had already found and reported two sections
above. A readiness report is read by somebody deciding whether a team is ready
to take the pager, and the only failure that really matters in a document like
that is a confident "fine". The page relation is already established,
deterministic, and the same one the coverage join uses.

The same reasoning drove `_alerts_for`: an `AlertRule` has no service field, and
attributing alerts by matching the alert's name against the service's name would
file `PaymentsApiHighLatency` under a service called `api`. Two exact routes
only — the alert's `runbook_url` resolves to one of the service's pages, or its
`team` label equals the catalog owner. Alerts reachable by neither appear in the
estate-wide coverage numbers and in no service's row.

## 2026-08-15 — reporting the agreements, not only the disagreements

**Question.** Multi-document consistency finds subjects two pages disagree
about. On the shipped corpus it finds none. Is there anything to report?

**Call.** Yes: the corpus has ten subjects documented on two pages each, all
agreeing, and the readiness report says so.

**Reasoning.** A consistency check that only speaks up on disagreement cannot
demonstrate it is working, and "no output" is indistinguishable from "not
implemented". Ten facts stated in two places and matching everywhere *is* the
result, and it is the check no single-document review performs — a page can be
internally consistent, correct against the estate, and still contradict the page
next to it. The divergence case is covered by a unit test with a register built
to contain one, rather than by planting drift in a corpus whose measurement key
was fixed at stage 1.
