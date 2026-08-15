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

## 2026-08-15 — MCP without an MCP library

**Question.** Stage 11 wants `analyze`, `propose`, `approve` and `apply` as MCP
tools. Take the dependency, or write the protocol?

**Call.** Write it. Three methods — `initialize`, `tools/list`, `tools/call` —
over line-delimited JSON-RPC on stdio, in about eighty lines.

**Reasoning.** Runtime dependencies here are httpx and pyyaml, and a framework
to expose four functions is a poor trade in a build whose argument is that its
moving parts are legible. The risk of hand-rolling a protocol is getting it
subtly wrong, so the two places that actually bite are tested rather than
assumed: a notification gets no reply at all, and one malformed line does not
kill the server.

The shape mattered more than the transport. The tempting design is one tool
called `fix_my_runbooks`, and it is wrong for the reason the whole project
exists — it moves the human decision inside the tool where nobody can see it.
Four tools in the same order a person works in, calling the same `ReviewQueue`
the terminal loop calls. There is a test asserting the server never calls
`register.decide` directly, because a second copy of the gate is exactly how the
machine path quietly acquires different rules from the human one.

Two things an agent cannot do, as code rather than as tool descriptions: there
is no approve-all (`finding_ids` is required and empty is an error), and
`propose` returns a price and spends nothing without `confirm=true`. An agent
loops; a description it did not read is not a control.

## 2026-08-15 — what the first live run found, and why the stub had hidden it

**Question.** The edit path was green against `tests/stub_superdocs.py` through
stage 12. What does running it against the real service change?

**Call.** Three things, and one of them means the path as shipped could never
have worked.

**Reasoning.**

**The synchronous chat turn is a dead end.** `POST /v1/chat` with
`approval_mode: ask_every_time` returns `requires_approval: true` and a list of
`change_id`s and **no job id at all**, while `/v1/chat/{s}/approve` requires
one — `422` without the field, `404 Job not found` when empty, and
`400 Job is not awaiting approval (status: completed)` for the `sync_chat` job
the turn actually created. So the operation is spent, the wording comes back,
and nothing in the API can ever accept it. `edit.propose_for_page` now uses
`/v1/chat/async`, whose job parks at `awaiting_approval`.

The lesson is about the stub, not the service. The stub had modelled the sync
reply as carrying a `job_id` — one invented field — and that single fiction kept
an unusable code path green through five stages. A stub is a hypothesis about a
service, and this one was wrong in the specific way that is hardest to notice:
it made the code look correct. The stub has been corrected to omit the field, so
the offline suite now exercises the path that works.

**Our own mapping was silently dropping correct changes.** The service returned
"Automated backup retention: 7 days" → "… 14 days", exactly right, and
`_replacement` returned empty: the diff covers the token `7`, the anchored value
is `7 days`, and the `asserted not in old_token` guard rejected it. The finding
then escalated as "no replacement text was produced", which reads like the model
declining rather than like a bug in this repository. Every corpus fixture
happens to anchor a single token, so no offline test could have caught it —
`test_a_multi_word_value_survives_the_mapping` is now a table rather than one
case, for that reason.

**Confluence normalises new content but not untouched bytes.** A sent `—` is
stored as `&mdash;`. That is only a curiosity until you notice what it would
mean if it applied to the whole body: every write would alter bytes outside the
approved passage, and the central promise of this project would be false through
no fault of the splice. It does not — a body PUT back unchanged returns
byte-identical — and that is now `test_live_an_untouched_body_survives_a_write`,
checked against a real page rather than assumed.

The through-line in all three: the offline suite was testing the code against my
model of the services, and two of the three failures were in the model. The
fixes worth keeping are the ones that moved a belief into a test.

## 2026-08-15 — the first live end-to-end run, and what a document's shape does to a model

**Question.** The edit path worked against one synthetic passage live. What
happens with seven real ones on a real Confluence page?

**Call.** Two changes to how a request is built, both forced by what came back.

**Reasoning.**

**Do not put machine identifiers in the document.** `build_passage_document`
wrote `<h2>Passage 1 — alert:PaymentsApiErrorBudgetBurn:threshold</h2>` above
each passage. The model edited the *heading* — `alert:X:threshold` became
`alert:X:0.05` — and five of seven findings came back with nothing usable. The
subject is a machine identifier that reads as prose containing the exact word
the instruction is about, so it was the most plausible thing in the document to
correct. The heading is now `Passage 1` and nothing else. Fix rate went from
2/7 to 4/5 on the same page.

The general lesson is worth more than the fix: everything in the document is a
candidate for editing, so the document should contain only what is allowed to
change. That is the same principle as rule 3 pointing the other way — there,
page text must not become an instruction; here, our metadata must not become
editable content.

**"Do not add commentary" holds most of the time.** The exceptions were
`'Payments Platform'` → `'Payments Platform is not a valid rota; valid rotas
are …'` and `'rollback-production'` → `"rollback-production (Note: … not a
valid CI job …)"`. Both correct, both helpful, and both would have been spliced
into the middle of a sentence in an operational runbook. `_sane` refuses a
replacement that still contains the value it was meant to replace, or that is
much longer than it. Refusing costs a human one look at an escalated finding;
accepting costs a paragraph of model prose inside an incident instruction.

**The wording layer is not deterministic and the checker is.** The same batch
of five passages returned 1/5, then 4/5, then 4/5 usable replacements. This is
not a defect to fix, it is a property to design around, and the design already
did: `propose_all` skips findings that already carry wording, so a re-run
retries only the failures at one operation per page. Two retries converged.
It does mean any measurement of *that* layer needs several runs, and the README
says so — a single run would have supported either "this works" or "this barely
works" depending on which one you did.

## 2026-08-16 — the walkthrough is a third script, not a mode of the other two

**Question.** The sibling build has three entry points: `mb` (the product),
`selftest` (unattended proof), `demo` (a paced walkthrough). This build had the
first two and a `demo/` *directory* holding the live-page seeder. Is a
walkthrough script worth its own file, or is it `selftest` with pauses?

**Call.** Its own file, and the directory was renamed out of the way — the
seeder is now `seed.py` at the root next to `preflight.py`, and its page lives
in `fixtures/live/`.

**Reasoning.** They are opposite artefacts. `selftest` exists so nobody has to
watch it: cheapest-first, pass/fail, live stages skipped loudly. `demo` exists
to be watched: one stage at a time, real output left on screen, every stage
printing its cost before it runs, nothing advancing without a keypress. Merging
them would make one of the two worse — a proof script that pauses cannot run in
CI, and a walkthrough that races cannot be narrated.

Two things the first end-to-end run of it taught, neither of which was visible
from running the commands by hand:

**The register spans sweeps, so a walkthrough needs two of them.** Stages 1-3
sweep the corpus and stages 4-12 sweep a live Confluence space. Sharing one
register left the corpus's findings — for pages 1001-1007, which exist only in
`fixtures/` — sitting in the queue when the live half ran, so `rr propose`
priced eight pages instead of one and `rr review` tried to write to Confluence
pages that do not exist. That is the register behaving correctly: it holds
findings until somebody decides on them, and two estates are two sets of
findings. The script now uses a register per half.

**A demo that hides the wording layer's variance is lying about the product.**
Stage 7 runs `rr propose --yes` twice, and says why in the stage label. One pass
worded three of seven findings; two passes worded six. Hiding that behind a
single lucky run would misrepresent the thing most likely to disappoint somebody
in week one — and showing it demonstrates the property that makes it survivable,
which is that a second pass costs one operation and retries only the failures.

## 2026-08-16 — two failures found by running the demo rather than the commands

**Question.** The individual commands had all been run live and were correct.
Was the walkthrough script just packaging?

**Call.** No — running them *as a sequence* found two things running them
individually could not, and one of them was a defect in my own code of exactly
the kind this project exists to catch.

**Reasoning.**

**`seed.py delete` reported success for a delete that never happened.**
`DELETE /wiki/api/v2/pages/{id}` answers `401 scope does not match` — a scoped
API token can create and overwrite a page but not delete one. The function
printed `delete 557058 -> 401` and returned normally, so `./demo` finished with
"walkthrough complete, and every stage passed" while the page sat in the space.
A tool whose entire argument is "a claim nobody verified is reported as
unverified" had a cleanup path that reported success for a refused request. It
now exits non-zero and prints what to click. This is the argument for demo
scripts: nobody reads the return code of a command they ran by hand and watched
succeed, and a script does nothing else.

**An open editor tab silently reverts API writes.** Page 98311 was left correct
at version 5 by a passing test and was 29 bytes twenty minutes later. Version 6
is labelled `Autosaved` — the Confluence web editor, open in a browser tab the
whole time, holding its copy from before any of the API writes and saving it
over the top. The version check does not help: it protects this tool from
overwriting somebody else, not the other way round, and the autosave is a
perfectly valid new version.

That is now the most important limitation in the README, because nothing in the
API exposes "a human has this page open" — the tool cannot detect it, refuse, or
warn. What it can do is what it already does: make every change one labelled
version that reverts in two clicks, and keep the number of writes small and
deliberate. Worth being blunt about rather than discovering in somebody's
production space.

## 2026-08-16 — a per-test thread-leak guard, after an incident caused by the same bug class

**Question.** The suite runs an in-process HTTP stub with a server thread. The
threads are daemons, so they cannot outlive the run. Is that worth a test?

**Call.** Yes — an autouse fixture that fails any test leaving a live
non-daemon thread behind, naming the test.

**Reasoning.** The prompt for this was an incident during the build: a machine
with all eight cores pinned at 100% by processes nothing obviously accounted
for. The cause was not in this repository — it was a shell command run by hand
while debugging the concurrency test:

    for i in $(seq 1 $(nproc)); do (while :; do :; done) & done
    LOADPIDS=$(jobs -p)
    kill $LOADPIDS 2>/dev/null; echo "load stopped"

`jobs -p` inside `$(...)` runs in a subshell that does not inherit the job
table, so it returned nothing, `kill` was called with no arguments, `2>/dev/null`
hid the error, and the line printed "load stopped" regardless. Eight infinite
busy loops survived for hours.

That is the *same failure* as `seed.py delete` reporting success for a `401`,
found the same day, and it is the failure this whole project is about: a
cleanup step whose failure is hidden, followed by a message asserting it
worked. Two instances in one build, both in throwaway cleanup code, neither in
the parts anybody was reviewing carefully — which is the point. Cleanup paths
are where unverified success claims live, because nobody is watching the thing
that is supposed to make nothing happen.

The guard does not prevent that class in shell scripts, and nothing can. What
it does is convert one specific "this cannot happen" into something checked on
every test, in the place where an accidental non-daemon thread would otherwise
be found later, from a process list, by somebody wondering why their laptop is
hot. Daemon threads are tolerated deliberately: untidy but harmless, since they
die with the interpreter. Non-daemon threads hold it open, and that is the one
that becomes an incident.
