# stylefix — a style-guide linter that fixes in place

Built on [SuperDocs](https://superdocs.app) for the SuperDocs engineer task
(assigned build 2.1, difficulty band S2), by **Sankalp Mallappa**.

A technical writer points it at a page and a style guide. It reports every violation
with the rule it breaks and the suggested rewrite, applies the fixes that are safe to
apply, and leaves code samples, tables and compliant headings untouched. Batch mode
runs a whole docs set and reports which guidance the team ignores most.

## The one design decision

**The model proposes; a deterministic guard disposes.**

Nothing reaches the document that has not been cleared by `guard.py`, which uses no
model at all. It extracts the document's visible text, remembers where every
character came from in the HTML, and refuses any change that lands in a protected
region — `<pre>`, `<code>`, `<table>`, `<script>`, or a heading already judged
compliant.

The guard fails closed. If it cannot locate a change unambiguously, it drops it and
says why. A missed fix is cosmetic; a wrong edit inside a code sample is the card's
explicit failure condition.

That mattered more than expected. An earlier version matched proposed text against
raw HTML, and on realistic prose it was wrong in both directions: it could not find
`The system utilizes a cache` when the word sat inside `<em>`, and it *would* have
edited `utilizes` inside a `<script>` block or an HTML attribute. Matching against
extracted text with an offset map back into the markup fixed both.

## Rules live in the attachment, not in the code

No rule is hardcoded. The style guide is uploaded as a SuperDocs attachment and is
the linter's entire ruleset. Two guides ship here, and they contradict each other on
purpose:

| Rule | `house-product-style.md` | `plain-english-public.md` |
|---|---|---|
| Contractions | `contractions-ok` — welcome | `no-contractions` — expand them |
| Interface verb | `ui-verbs` — *select* | `click-is-fine` — *click* |
| Headings | `sentence-case-headings` | `title-case-headings` |

Swapping `--guide` changes what the linter finds. No code path branches on which
guide is in use, and `test_flow.py::test_swapping_the_guide_changes_behaviour_with_no_code_change`
asserts it rather than claiming it.

## Use

```
export SUPERDOCS_API_KEY=your-key-here

# report only
python -m stylefix.cli lint docs/webhooks.md --guide styleguides/house-product-style.md

# apply what the guard clears, then export
python -m stylefix.cli lint docs/webhooks.md \
    --guide styleguides/house-product-style.md --apply --export docx

# whole docs set, five documents, stop after 20 operations
python -m stylefix.cli batch docs/ --guide styleguides/plain-english-public.md \
    --sample 5 --max-ops 20
```

Batch defaults to reporting without editing: the first question a docs lead asks is
which guidance is being ignored, not "please rewrite 400 pages". `--sample` is
deterministic, so a sampled run is reproducible, and `--max-ops` stops the run and
names the documents it did not attempt.

Real output from a live run over three pages on 2026-08-19:

```
Style guide : house-product-style.md
Documents   : 3 linted, 0 failed, 0 skipped
Operations  : 3
Mode        : report only, nothing applied

Violation profile, most-broken rule first:
  rule                              found  cleared   refused
  unattributed                          2        0         2
  no-filler                             1        1         0
  plain-verbs                           1        0         1
```

The second column is `cleared`, not `applied`, when the run is report-only — nothing
was approved, and labelling it "applied" would overstate what happened.

## Findings name the rule that fired

The API carries no rule id on a proposed change (see *Known limitations*), so
attribution is derived here from triggers the guide declares:

```
- `plain-verbs: utilize, utilizes, initiate, terminate`
- `no-filler: in order to, at this point in time, basically, simply`
```

A trigger counts only if the edit actually *removed* it — a word still present
afterwards was not what the fix was about — and the most specific trigger wins, so
`in order to` beats a shorter match inside the same edit. A change that alters only
capitalisation is attributed to the guide's heading rule, which no word list can
express. `test_rules.py` fixes all of this against the live payload.

## What has actually been run

Stated plainly, because a build that looks complete and has never executed is worse
than a small one that has.

**A full live run was made on 2026-08-19** against the real API — upload, attach a
style guide, `chat_async` with `approval_mode='ask_every_time'`, per-change approve
and deny, export. Every raw response is committed under `tests/fixtures/`, and six
tests in `test_live_fixture.py` are driven by those payloads rather than by anything
hand-written.

That run changed the design. The live `pending_changes` carries `old_html` and
`new_html` for a whole chunk — **not** the `original`/`replacement` text span the code
had assumed from the OpenAPI schema. Against the real payload the parser produced
empty targets and the guard refused everything, so the linter would have applied
nothing and reported a clean document. Nothing offline would have caught it.

| Path | Status |
|---|---|
| Upload, attachment, `chat_async`, approve, export | **Run live 2026-08-19.** Fixtures committed |
| `guard.py` — protection, matching, fail-closed decisions | **Verified.** 19 offline tests plus 3 against the real document HTML |
| `parsing.py` — envelopes, double-parse, chunk-HTML diffing | **Verified** against the captured `get_job` payload |
| `lint.py` / `batch.py` / `cli.py` — the flow | **Run live 2026-08-19.** `stylefix batch` over three pages and `stylefix lint --apply --export` end to end |
| Batch mode over a real docs set | **Run live.** 3 documents, 3 operations, profile below |
| Export writing a file to disk | **Run live.** A 36,827-byte, 17-part `.docx` written to disk and validated as OOXML |
| Rule attribution | **Verified** against the live payload (`test_rules.py`) |
| Pre-signed upload (>100 KB) | **Run live.** A 244 KB PDF through the signed URL. Needed two fixes: the `PUT` must carry a `Content-Type` matching the ticket, and `/process` needs `filename` |
| Screenshot | **Missing** |

61 tests, no key and no network.

## The live run, in full

Input, with two traps — a violation inside a code sample and one inside a table cell:

```html
<h1>Configuring The Webhook</h1>
<p>In order to configure the webhook, please click Save. The service utilizes a cache to store events.</p>
<pre><code>client.utilize(please=True)  # do not rewrite this</code></pre>
<table>… <td>utilize the default</td> …</table>
<p>At this point in time you should terminate the session.</p>
```

Result after approving the prose fixes and denying the heading:

```markdown
# Configuring The Webhook                  ← heading denied; unchanged

To configure the webhook, please click Save. The service uses a cache to store events.

    client.utilize(please=True)  # do not rewrite this   ← code sample untouched

| retries | utilize the default |          ← table cell untouched

Now you should end the session.
```

`in order to` → `To`, `utilizes` → `uses`, `terminate` → `end`, `At this point in
time` → `Now`. The two `utilize`s inside the code sample and the table cell were left
alone, which is the whole claim.

A few rough edges turned up during that run. They are reported to the SuperDocs team
directly rather than listed here, since a public repository is the wrong place for
someone else's bug tracker. Two of them shaped this code and are visible in it: the
approve step deliberately sends no feedback on a denial, and the wait after approval
is bounded rather than open-ended.

## Known limitations

- **A run is not reproducible.** Observed 2026-08-19: the same page, the same guide
  and a byte-identical instruction produced three proposed changes in one run and
  none minutes later. So "no changes proposed" cannot be read as "the document
  complies", and the CLI says exactly that rather than claiming a clean bill. For a
  docs team this is the sharpest limitation: the violation profile is not stable
  between nightly runs. Written up in the bug log.
- **Some findings stay unattributed.** Attribution fires on triggers the guide
  declares, so an edit the guide has no word list for — a rewritten sentence, a
  passive-voice fix — lands under `unattributed`. That is honest rather than guessed,
  but it thins the profile. Two of five findings in the live batch were unattributed.
- **Multiple edits in one chunk collapse into one span.** `derive_edit` returns the
  smallest contiguous text difference, so a paragraph fixed for two rules yields one
  wide original/replacement pair and is attributed to the more specific trigger only.
- **Headings are protected by default.** Compliance cannot be judged without knowing
  the rules, so every heading is refused unless the change's rule is named on the
  guide's `heading_rules:` line.
- **Ambiguity is refused, not resolved.** A phrase appearing twice inside one chunk
  is dropped. Chunk scoping removes most of this; the rest is deliberate.
- **No `templates` or `Review` surface.** The card lists five; this build uses chat,
  API and export.

## What it uses from SuperDocs

| Feature | How |
|---|---|
| **Document upload** | `POST /v1/documents/upload-base64` under 100 KB, and the pre-signed `/v1/uploads` flow above it. Chunk ids are read from the `data-chunk-id` attributes on the returned HTML |
| **Attachments** | The style guide is uploaded as an attachment and polled to `completed` before linting, so the model is never asked to apply rules that have not loaded |
| **Chat (async)** | `POST /v1/chat/async` with `approval_mode='ask_every_time'`, which is the only surface that pauses before anything is written |
| **Review / approval** | `POST /v1/chat/{session}/approve`, one decision per change, so the guard's refusals and approvals are per-item |
| **Export** | `POST /v1/documents/export` to `.docx`, written to disk |

Everything is REST with an `sk_` key. The card allows either surface; REST was chosen
so the linter runs as a standalone program a docs team could put in CI, rather than
needing an MCP client attached.

## Credit

Built by Sankalp Mallappa for the SuperDocs engineer task. MIT, matching the
`superdocs-builds` repository.
