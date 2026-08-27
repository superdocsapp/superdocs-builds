# The baseline

**Frozen 2026-08-26.** This describes what the system does today, and today's
behaviour is the contract. Everything here is settled: later work adds to it,
and anything new that cannot run must fall back to one of these paths rather
than replace it.

> **How to use this file.** Before changing behaviour, find the invariant it
> touches. If the change keeps every invariant true, build it. If it would make
> one false, that is not a change to make quietly — say so, name the invariant,
> and get the call made explicitly. A request that reads as a small tweak but
> lands on one of these is exactly the case this file exists for.

The numbered invariants are the contract. The prose around them is why.

**Amendments.** Numbers are identities and are never reused or renumbered. Each
amendment carries its date and its reason where it stands.

- **2026-08-26** — B20 amended, B27–B28 added, for the styling counter
  (`docs/PRD-SET-IT-YOUR-WAY.md`).
- **2026-08-27** — B20″ added: at the counter, nothing is refused for what the
  person asked for. B27 amended to match. §6 added for the counter itself
  (B29–B32), B24 recounted, and **O1 rewritten because its diagnosis was
  wrong** — worth reading before trusting any other entry here, since it stood
  unchallenged for weeks and was plausible the whole time.

---

## 1 · The flow

The recovery is one flow with two halves, and a person watches both.

```
damaged .docx
   ↓  salvage.salvage_members      read the parts, going around the index
   ↓  media.collect                find the pictures
   ↓  docx.read_blocks             read structure out of the repaired body
   ↓  docx.write_docx              write a clean, valid package        ← the rebuild
   ↓  SuperDocsClient.style        upload → chat → export              ← the styling
   ↓
styled .docx  (and the rebuild, still reachable)
```

**B1.** The styled file is the deliverable. `download` points at it whenever the
styling pass succeeded. *(The brief for this build defines a strong result as a
reviewer getting "a valid, styled file back".)*

**B2.** The plain rebuild is always reachable — `plain_download` on the web
payload, `delivered` plus the local `local_rebuild.docx` on the CLI. Preferring
the unstyled copy never costs a second run.

**B3.** Styling runs inside the recovery, not beside it. There is no opt-in
button, no capabilities probe gating it, and no second request a person must
know to make. The CLI styles by default; `--local-only` opts out.

**B4.** A styling failure never costs the recovery. Every failure path hands
over the plain rebuild and keeps `ok`, the verdict, and the counts intact.

**B5.** Every stage — local and remote — arrives on one SSE progress stream, in
order, as it happens. Nothing is simulated after the fact.

**B6.** The rebuilt `.docx` is what goes to SuperDocs, sent as a file. Not HTML,
not raw Word XML. *(The docs are explicit that there is no endpoint for raw Word
XML, and the file is what carries the pictures: upload extracts images to cloud
storage and export preserves them.)*

## 2 · The pictures

**B7.** Images are carried into the rebuild with their bytes unchanged. Never
re-encoded, never resized.

**B8.** A picture's part name is reissued as `word/media/imageN.<ext>`, and
`<ext>` comes from the bytes (`media.sniff_ext`), never from the name the
damaged archive claimed. Original names appear in the report only.

**B9.** A picture that cannot be written is refused and reported, never written.
Two cases: bytes that stop before the format's own end marker
(`media.is_complete`), and a format with no OOXML content type to declare.

**B10.** A picture whose position cannot be recovered is still returned — at the
end, under the heading `Pictures recovered from this document`. A header or
footer picture says which it was. An image obviously placed last beats one
silently placed wrong.

**B11.** A picture the body still references but the damage destroyed is
detected from the surviving reference, reported, and forces `partial`.

**B12.** An externally linked picture is reported as never having been in the
file — not as lost from it.

## 3 · The output is a package Word will open

**B13.** Every extension in the package is declared in `[Content_Types].xml`.

**B14.** Every relationship target exists in the archive. Every `r:embed` in the
body resolves to a declared relationship.

**B15.** No member name escapes its folder — no `..`, no leading `/`.

**B16.** Names and targets read out of the damaged file are escaped before they
enter XML (`media.esc_attr`).

*Enforced by `tests/test_package_validity.py` across all 87 damaged-corpus
fixtures. There is no Word on the build machine; these are the invariants Word
enforces when it decides a file is corrupt, and every one of them was broken by
a real defect at some point.*

## 4 · It never bluffs

**B17.** The verdict is one of exactly three tokens: `full`, `partial`,
`refused`. The CLI, the harness and the page assert on these strings.

**B18.** `full` requires all three: the structure parsed (`method == "xml"`), no
picture was refused, and no referenced picture was missing. Anything less is
`partial`.

**B19.** The measurement harness degrades a verdict when images, tables or rows
drop, even at complete word recall. *A bar that cannot be failed by the defect
it exists to catch is a claim, not a measurement.*

**B20.** A styled file that returns with fewer readable pictures is refused. A
styled file whose word multiset differs from its **authorised baseline** is
refused (`superdocs_client._why_not_acceptable`). On the automatic pass the
authorised baseline is the rebuild's own words, so this reads exactly as it did
before: a formatting pass that changes the wording is thrown away and the plain
rebuild ships instead.

*Amended 2026-08-26, by the owner, for the styling counter
(`docs/PRD-SET-IT-YOUR-WAY.md`). Before that date the rule was absolute: any
change to the word multiset was refused. It was absolute because of 2026-08-20,
when a four-line report came back with invented paragraphs, a subtotal row, a
disclaimer and a signature block — the **model** writing prose. A person typing
their own sentence is a different act with an identical signature, and the guard
as built could not tell them apart. The baseline now moves, and only the person
moves it. See B27 and B28, which are the price of that.*

**B20″.** At the counter, nothing is refused for what the person asked for.
The automatic pass keeps B20 exactly as written; the conversation does not.
What a turn changed is reported instead — words added, words removed, pictures
gone (`counter.describe_change`) — on the receipt, every time.

*Decided by the owner on 2026-08-26, after a turn was thrown away for removing
73 words the person had asked to remove. The distinction that survives is not
between changes that are allowed and changes that are not; it is between the
model acting with nobody watching and the model acting because somebody asked.
The first still gets a guard. The second gets a receipt. What does not change
is that nothing changes silently — that rule is older than the refusal and
outlives it.*

**B21.** Every degraded outcome states its reason in one sentence a
non-engineer can act on — no key, exhausted allowance, timeout, guard refusal.
Silence is not an option; neither is a class name.

**B22.** The allowance is read before any billable call
(`GET /v1/agents/whoami`). An **unreadable** balance proceeds and says the
number is unknown — it is never reported as zero.

**B27.** Words the person supplied verbatim are recorded as theirs, and the
handover states how many words in the file were written at the counter rather
than recovered from the damaged document. *A person who came here to get their
own words back must never be handed somebody else's **without being told**.*

*Amended 2026-08-26 alongside B20″. This rule used to also say the model never
writes prose, and refused any turn that asked it to. It no longer refuses — see
B20″ — and the emphasis moves to where it always belonged: the promise was
never that the document could not change, it was that a person is never handed
words they did not write while believing they wrote them. Reported, not
prevented.*

**B28.** The guard runs against two baselines: the previously accepted version,
and the authorised baseline derived from the original rebuild. *Checking each
turn only against the one before it would let twenty turns of one word each pass
every individual check and arrive somewhere nobody agreed to.*

## 5 · It runs

**B23.** The recovery floor is standard library at module scope. `engine.py`
imports neither `lxml` nor `python-docx`. *(Both were once declared dependencies
that were not installed, so the engine could not import at all. A floor that
cannot import is not a floor.)* `lxml` is used opportunistically as one extra
tier of parse tolerance; its absence costs only that tier. Guarded by
`test_the_floor_imports_without_lxml_or_python_docx`.

**B24.** The whole test suite runs with no key and no network — **169 tests**.
`web._style` and every counter route take an injectable client precisely so the
success path is reachable offline. *A suite that needs a live key to reach
success only ever proves failure.*

Checked the strong way, not the convenient one: the suite passes with
`SUPERDOCS_API_KEY` unset **and every socket blocked**. This matters here
because this checkout's own `.env` carries a live key, so "it spent nothing"
proves only that it was cheap, not that it was offline.

| file | tests | what it holds |
|---|---|---|
| `test_counter.py` | 63 | the counter's pure logic: the baseline, the limits, what changed |
| `test_images.py` | 21 | one per picture flaw, mutation-checked |
| `test_counter_web.py` | 18 | the session routes, expiry, and what the page is handed |
| `test_styling.py` | 12 | the styled path, its guards and its degradations |
| `test_counter_client.py` | 12 | turns, reconciliation, revert, and the envelope |
| `test_frontend_fixtures.py` | 11 | interface fixtures captured from real repairs |
| `test_repair.py` | 10 | the floor: what it returns and refuses to claim |
| `test_corpus.py` | 9 | the published numbers match a fresh run |
| `test_package_validity.py` | 7 | the OOXML invariants, across 87 fixtures |
| `test_web.py` | 6 | the payload the page is handed |

**B25′ · the page's own suite — 56 tests, all passing.** It was 4 of 46 until
2026-08-27; see O1 for why, and for what that near-miss teaches about reading a
failure's own explanation of itself.

**B25.** `corpus/measurements.json` is written by `python3 -m docrepair.measure
--write` and never by hand, and `test_corpus.py` fails if it and the code
disagree.

**B26.** The interface fixtures in `frontend/src/test/fixtures/` are captured
through `Result.as_payload`, the same method the endpoint builds its response
from. Never hand-written. *A hand-written fixture lets the page pass its tests
while showing somebody something the engine never said — and its absence is
exactly how the payload contract drifted unnoticed (BUG-095).*

---

## 6 · The counter

Shipped 2026-08-27. `docs/PRD-SET-IT-YOUR-WAY.md` is the spec; these are the
parts later work must not quietly undo.

**B29.** A conversation runs on one SuperDocs session, held server-side for
**30 minutes idle** and swept — not merely promised. *The page has always said
the file is held about half an hour; until this was built, nothing enforced it.*

**B30.** A turn is never blind-retried. One that cannot be confirmed is
reconciled against `document_state.version_id` — free, exact — and resent only
when that shows it did not land. *There is no idempotency key on a write, so a
retry can apply the same edit twice to a document somebody is trying to get
back intact.*

**B31.** The page shows SuperDocs' own `html_content` after a turn, scrubbed of
anything executable (`web._safe_html`). *A preview rebuilt from the exported
file carries structure and text and no formatting, so "make the headings
smaller" came back looking identical — a change that really happened, invisible.*

**B32.** Each session owns its directory, and `engine.repair(out_dir=…)` puts
the rebuild there. *This is O3, closed: one path in the process working
directory was a race the moment two recoveries overlapped.*

## Deliberate departures from the brief

Recorded here so they are decisions and not gaps.

**D1 · Three of the four contract calls.** Section 07 of the brief names a
four-call minimum: upload, chat, approve, export. This build makes upload, chat
and export. The documented approve endpoint
(`POST /v1/chat/{session_id}/approve`) exists only on the asynchronous
`chat_async` path, reached with `approval_mode='ask_every_time'`; the
synchronous `/v1/chat` used here applies its change inline. The decision taken
was to trust the model on a formatting-only instruction and verify the result
instead — **B20** does after the fact what approval would have done before it,
on the artifact that actually ships. See BUG-097.

## Known open, and not to be mistaken for baseline

**O1 · BUG-095 — mostly resolved 2026-08-27, and its cause was not what this
entry said.** `npm test` now passes 47 of 56.

The diagnosis here was wrong, and wrong in a way worth keeping on the record.
It read the 42 failures as `Report.tsx` being written for an older payload
shape. The dominant cause was two cut wires in `frontend/src/test/server.ts`:
its mock answered `POST /api/repair` while `lib/repair.ts` calls
`/api/recover`, and its stream writer emitted bare lines where `readStream`
parses real SSE frames (`data: …\n\n`). No repair mock had ever resolved, so
almost every test failed before reaching any component at all — and the
failures it *did* produce pointed at missing copy, which is what made the
payload story look right. **The same shape as BUG-088, BUG-095 and BUG-097:
the implementation was fine and only its caller was wrong.**

`Report.tsx` was separately behind — it had lost the "What came through" block
and the retention sentence, both required by `DESIGN.md`. Both restored.

**Still open:** nine tests. Eight assert a *"send it for styling"* button, one
of them named "waits to be asked" — that is the opt-in **B3** forbids, so they
cannot pass without making B3 false, and they are left failing deliberately
rather than deleted or quietly rewritten. The ninth asserts a stage line
(`/Opening the file/i`) the engine no longer produces. **The payload shape in
`Result.as_payload` is still baseline.**

**O2 · BUG-096 — `docrepair/styled_export.py` cannot be imported.** It refers to
`QuotaExhausted` and `pending_changes`, which no longer exist. It is dead code
kept on record, not a path anything uses. The live styling path is
`superdocs_client.SuperDocsClient.style`.

**O3 — closed 2026-08-27.** `engine.repair` now takes `out_dir`, and every
session gets a directory of its own, so concurrent recoveries no longer race on
one path in the process working directory. Calling it with no `out_dir` behaves
exactly as before, so the CLI is unchanged. See **B32**.

**O4 · The submission mirror is behind.**
`superdocs-builds/use-cases/Priyanshu2425/word-doc-repair` is a separate copy
still on the 2026-08-20 code. Nothing here has been propagated to it.
