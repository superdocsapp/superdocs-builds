# BUGS.md

Rough edges hit while building Runbook Reconciler, in the shape the task
document asks for: what I did, what I expected, what happened instead, how badly
it blocked, and how to reproduce it.

**This list is short, and the reason is worth stating up front.** The
SuperDocs API surface this build uses — upload, chat, approve, export — was
already mapped by the sibling build in
`use-cases/CulturalProfessor/product-manual-builder`, whose `BUGS.md` carries
twenty-one items against it. The client here is that file, copied. So the
findings below are about the *other* half of this project: Atlassian's Confluence
Cloud API, which nothing in the sibling build touched.

Everything below was verified against a live Confluence Cloud site on
**2026-08-15** with a **scoped** API token. No key appears in this file; every
snippet uses `$CONFLUENCE_API_TOKEN`.

**Item 4 is the one that changed a design.** The others cost time; that one made
a mechanism in the build plan impossible and forced a different, better one.

---

## 1. A scoped API token is rejected by the site host and works only through the gateway

**What I did.** Authenticated against `https://<site>.atlassian.net/wiki/api/v2/pages`
with basic auth — email plus a scoped API token created at
`id.atlassian.com/manage-profile/security/api-tokens`.

**What I expected.** `200`, or an error naming a missing scope.

**What happened.** `401`, with a body indistinguishable from a revoked or
mistyped credential. The same token against the gateway host works:

| Host | Basic | Bearer |
| --- | --- | --- |
| `https://<site>.atlassian.net` | 401 | 403 |
| `https://api.atlassian.com/ex/confluence/{cloudId}` | **200** | **200** |

**How badly it blocked.** An hour, and it would have been much longer without
the guess that the host was the variable. Every piece of advice you find while
searching says to check the token, which is the one thing that was fine. A
`401` that means "right credential, wrong host" is the single most expensive
error message in this API.

**How to reproduce.**

```bash
SITE=https://your-site.atlassian.net
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$SITE/wiki/api/v2/pages?limit=1" -o /dev/null -w '%{http_code}\n'   # 401

CLOUD_ID=$(curl -s "$SITE/_edge/tenant_info" | python3 -c 'import json,sys;print(json.load(sys.stdin)["cloudId"])')
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "https://api.atlassian.com/ex/confluence/$CLOUD_ID/wiki/api/v2/pages?limit=1" \
  -o /dev/null -w '%{http_code}\n'                                      # 200
```

**Worked around.** `reconciler/confluence/client.py:discover()` resolves
`cloudId` from `/_edge/tenant_info` (no auth needed) and then probes all three
combinations, using whichever answers `200` — so a classic token, which does
work against the site host, still works.

---

## 2. CQL search is unreachable with a scoped token, and there is no v2 replacement

> **Corrected 2026-08-15.** This item originally claimed the v1 REST API was *entirely*
> unreachable. That is wrong, and I found out by accident when `seed.py` successfully
> added a label through a v1 endpoint. Reachability follows the token's granted scopes
> endpoint by endpoint:
>
> | v1 endpoint | Result |
> | --- | --- |
> | `GET /wiki/rest/api/content/search` | 401 |
> | `GET /wiki/rest/api/content/{id}` | 401 |
> | `GET /wiki/rest/api/user/current` | 401 |
> | `GET /wiki/rest/api/space` | 401 |
> | `GET /wiki/rest/api/content/{id}/label` | **200** |
> | `POST /wiki/rest/api/content/{id}/label` | **200** |
> | `DELETE /wiki/rest/api/content/{id}/label/{name}` | **204** |
>
> The label endpoints work because `read:label` and `write:label` are on the token. So the
> lesson is not "v1 is dead" but "check the scope for the exact endpoint" — and it matters
> practically, because v1 labels are the *only* way to add a label to a page. The finding
> below stands for CQL search specifically; the generalisation did not.


**What I did.** Called `GET /wiki/rest/api/content/search?cql=label="runbook"`
through the working gateway host, to find every page carrying a label in one
request.

**What I expected.** `200` and a result set. CQL search is how the Confluence
documentation tells you to do this, and there is no v2 equivalent.

**What happened.** `401 Unauthorized; scope does not match`, through the gateway
that serves v2 successfully in the same session with the same header. The v2 paths
this build needs — `pages`, `pages/{id}/labels`, `labels`, `spaces` — all work, and
there is no v2 equivalent of CQL search to move to.

**How badly it blocked.** Half an hour, and it left a permanent performance
scar. Label filtering is now client-side: list the pages, then fetch each page's
labels, which is **one extra HTTP call per page in the space**. On a large space
that is the dominant cost of a sweep. It is also why `rr watch` compares a page
list rather than re-crawling.

**How to reproduce.**

```bash
BASE=https://api.atlassian.com/ex/confluence/$CLOUD_ID
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$BASE/wiki/rest/api/content/search?cql=label%3D%22runbook%22" \
  -w '\n%{http_code}\n'          # 401 Unauthorized; scope does not match
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$BASE/wiki/api/v2/pages?limit=1" -o /dev/null -w '%{http_code}\n'    # 200
```

**Worked around.** `ConfluenceSource.pages()` lists via v2 and filters labels
per page. Documented in that method rather than only here, because the person
who will care is reading that method wondering why it is N+1.

**Also fixed in the correction above:** adding a label is only possible through v1,
which the original over-broad claim would have ruled out. `seed.py` labels the
page it creates, and without that the page is invisible to `rr` — it crawls by label.

---

## 3. `401 Unauthorized; scope does not match` is returned for scopes the token has

**What I did.** Granted `read:user:confluence` on the token specifically so the
tool could learn its own `accountId`, then called
`GET /wiki/api/v2/users/current`.

**What I expected.** `200` and an account id, or an error naming the scope I was
missing.

**What happened.** `401 Unauthorized; scope does not match` — the same message
returned for the v1 endpoints in item 2, which the token genuinely has no access
to. So the message does not distinguish "you did not grant this scope" from
"this scope cannot be granted to this kind of token", and there is no way from
the response to tell which situation you are in.

**How badly it blocked.** An hour of re-issuing tokens with different scope
combinations, on the assumption that the message meant what it says.

**How to reproduce.** Grant `read:user:confluence`. Then:

```bash
BASE=https://api.atlassian.com/ex/confluence/$CLOUD_ID
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$BASE/wiki/api/v2/users/current" -w '\n%{http_code}\n'   # 401 scope does not match
```

**Not worked around, because it cannot be.** See item 4.

---

## 4. There is no way for an API token to learn its own account id — which broke the plan's mechanism for "ignore your own writes"

**What I did.** This build must never re-trigger on its own writes: a sweep can
end in a page being edited, that edit bumps the page's version, and the watcher
sees a changed page and sweeps again, forever. The plan's mechanism was to read
`version.authorId` from the page payload and ignore versions authored by us.

**What I expected.** One call to find out who "us" is.

**What happened.** Every route is refused:

| Endpoint | Result |
| --- | --- |
| `GET {gateway}/wiki/api/v2/users/current` | `401 Unauthorized; scope does not match` |
| `GET {gateway}/wiki/rest/api/user/current` | `401 Unauthorized; scope does not match` |
| `GET https://api.atlassian.com/me` | `401 Unauthorized` |

with `read:user:confluence` granted. The underlying reason appears to be that
`/me` needs `read:me`, an Atlassian **account** scope rather than a Confluence
**product** scope, and the API-token scope picker offers only product scopes.

The frustrating part is that the data is right there — `version.authorId` is
returned on every page in the v2 list response. The payload has the answer; the
token cannot learn what to compare it to.

**How badly it blocked.** It did not block: it forced a redesign, and the
replacement is better. `reconciler/register.py` gained a `page_writes` table
recording the exact version number each of our own PUTs returned, written in the
same transaction that marks the finding applied. The watcher asks
`register.wrote_version(page_id, version)`.

That is stronger evidence than the author id would have been. An author id only
establishes that the integration account made the edit — a colleague using the
same service account is indistinguishable from the tool. A version number
establishes that this exact version is the one our own write produced.
`account_id()` is kept as a second filter for classic tokens, where it does
work, and is never the only one.

**How to reproduce.**

```bash
BASE=https://api.atlassian.com/ex/confluence/$CLOUD_ID
for p in /wiki/api/v2/users/current /wiki/rest/api/user/current; do
  curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" "$BASE$p" -w " <- $p\n"
done
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" https://api.atlassian.com/me -w '\n'
# then confirm the data you cannot use is present:
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" "$BASE/wiki/api/v2/pages?limit=1" \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["results"][0]["version"])'
# {'number': 1, 'authorId': '...', ...}
```

---

## 5. Confluence has no per-block update, so "nothing else changed" cannot be delegated to the API

**What I did.** Looked for a way to update one paragraph of a page.

**What I expected.** Some form of PATCH against a block or a fragment. The
editor plainly has block-level operations.

**What happened.** There is no such endpoint. `PUT /wiki/api/v2/pages/{id}`
takes the **entire body** and an incremented `version.number`. Every update is a
whole-page replacement.

**How badly it blocked.** It did not block so much as define the build. The
central guarantee of this project — every byte outside the approved passage is
unchanged — cannot be obtained from the API and has to be constructed:

1. parse the storage format **only to locate** the target node's character range;
2. splice the original string at those offsets, so everything outside is
   byte-identical *because it was never re-serialized* — including macros the
   tool does not understand;
3. before the PUT, diff old against new and assert exactly one contiguous range
   differs, and that it is the intended one;
4. refuse to write otherwise.

The tempting alternative — parse to a tree, modify, re-serialize — reformats the
page, mangles `<ac:structured-macro>`, and is how you silently vandalise a
four-year-old wiki.

**Not a bug, and it is here deliberately.** It is the API constraint that shaped
the design more than any other, and anybody attempting this needs to hit it on
page one rather than after writing a tree serializer.

---

## 6. Pages created in the new editor are returned by the pages API — an expectation that turned out to be wrong

**What I did.** Assumed pages authored in Confluence's newer editor might not
appear in `/wiki/api/v2/pages`, or might return an empty `storage` body, and
planned a fallback around it.

**What happened.** They are returned, and `?body-format=storage` gives classic
XHTML — `<table data-layout="default">`, `<ac:structured-macro>` and the rest.
Page `98311` reads as 5,653 bytes of storage format.

**How badly it blocked.** Not at all, and it is recorded because the wasted work
was planning for it. A day of build time was reserved for a fallback that was
never needed.

**How to reproduce.**

```bash
curl -su "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" \
  "$BASE/wiki/api/v2/pages/98311?body-format=storage" \
  | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["body"]["storage"]["value"]))'
```

---

## 7. A synchronous `/v1/chat` turn proposes changes that can never be approved

**This is the most serious item in this file.** Verified live 2026-08-15.

**What I did.** `POST /v1/chat` with `approval_mode: "ask_every_time"`, then tried to
approve the changes it proposed.

**What I expected.** The reply carries whatever identifier the approval endpoint needs.

**What happened.** It does not. The synchronous reply is:

```json
{ "session_id": "...", "response": "I've prepared changes for your review...",
  "document_changes": { "pending_changes": [ { "change_id": "...", ... } ],
                        "requires_approval": true, "updated_html": null, "version_id": null },
  "usage": null, "hint": null }
```

`requires_approval: true`, a `change_id` per change — and **no `job_id` anywhere**. But
`POST /v1/chat/{session_id}/approve` requires one:

| Attempt | Result |
| --- | --- |
| omit `job_id` | `422 {"type":"missing","loc":["body","job_id"]}` |
| `job_id: ""` | `404 Job not found` |
| `job_id` from `GET /v1/sessions/{id}/jobs` | `400 Job is not awaiting approval (status: completed)` |

That last row is the closing of the trap. The sync turn *does* create a job — `job_type:
"sync_chat"`, `status: "completed"` — and approve rejects it precisely because it is not
parked. So there is no reachable identifier: the operation is spent, the wording comes
back, `requires_approval` is true, and nothing in the API can ever accept it. The stored
document keeps the old text for ever.

**How badly it blocked.** It was shipped. Every offline test passed because the stub had
modelled the sync reply as carrying a `job_id` — one invented field, and an entire code
path that cannot work in production was green all the way through stage 12.

**How to reproduce.**

```bash
# upload a document, then:
curl -s -X POST https://api.superdocs.app/v1/chat \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY" -H 'Content-Type: application/json' \
  -d '{"message":"replace 800ms with 1.2s","session_id":"'"$S"'","document_id":"'"$D"'","approval_mode":"ask_every_time"}' \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print("job_id" in r, sorted(r))'
# False ['document_changes', 'hint', 'response', 'session_id', 'usage']
```

**Worked around.** `edit.propose_for_page` uses `POST /v1/chat/async`, whose job parks at
`awaiting_approval` and approves cleanly. The stub was corrected to drop the invented
field, so the offline suite now exercises the path that works.

**What would fix it.** Either return `job_id` on the sync reply, or let
`/v1/chat/{session}/approve` accept `change_id`s without one. As it stands,
`approval_mode: "ask_every_time"` on the sync endpoint is a dead end that costs an
operation to discover.

---

## 8. `approve` reports success about three seconds before the stored document agrees

**What I did.** Approved a parked batch, then immediately read the document back with
`GET /v1/documents/{durable_id}?include_html=true` to confirm the change landed.

**What I expected.** `{"status":"ok","batch_complete":true}` to mean the document holds
the change.

**What happened.** The immediate read returns the **old** text. The same read about three
seconds later returns the new one.

```
approve -> {"status": "ok", "message": "Approval processed", "batch_complete": true}
  t+ 0s  1.2s=False  800ms=True
  t+ 3s  1.2s=True   800ms=False
```

**How badly it blocked.** An hour, and it nearly produced a much worse bug than itself.
This project reads the document back specifically so it can say "the service said it
applied the change and the stored document does not contain it". With a single immediate
read that sentence is true on every successful run, so the honest check becomes a
permanent false alarm — and the obvious fix, deleting the check, throws away the one thing
that would catch a real failure.

**Worked around.** `edit._stored_after_approval` polls until the stored passages stop
matching the pre-edit text, bounded, then falls back to the reply. Same shape as items 2,
10 and 20 in the sibling build's `BUGS.md`: a write returns `200` and a different read
endpoint disagrees with it for a short window. This is a fourth endpoint pair with the
same behaviour.

---

## 9. Confluence normalises entities in new content, but leaves untouched bytes alone

**What I did.** Appended `<p>runbook-reconciler live test — removed immediately</p>` to a
page and read it back.

**What I expected.** The bytes I sent.

**What happened.** The em dash came back as `&mdash;`. Confluence rewrites content on the
way in.

**Why this mattered more than it looks.** The central promise of this project is that
every byte outside the approved passage is unchanged. The splice guarantees that about
what the tool *sends*; it can guarantee nothing about what Confluence chooses to *store*.
If this normalisation applied to the whole body, every write would silently alter content
outside the target passage and the promise would be false through no fault of the splice.

**It does not.** A body PUT back unchanged returns byte-for-byte identical — verified
against page 98311. The normalisation applies only to content newly introduced. The
practical residue is small: a proposed replacement containing an em dash, smart quote or
non-breaking space will be stored in entity form, so it will not match the literal string
on a later read.

**How badly it blocked.** Twenty minutes, and it turned into the test I most wanted and
had not written: `test_live_an_untouched_body_survives_a_write`, which checks the property
the whole design rests on against a real site rather than assuming it.

---

## 10. The model edits whatever in the document looks most like the instruction, including headings

**What I did.** Sent a document of the shape `<h2>Passage 1 — alert:PaymentsApiErrorBudgetBurn:threshold</h2><p>…the passage…</p>`, with an instruction naming passage 1 and the value to correct.

**What I expected.** The paragraph to be edited.

**What happened.** The **heading** was edited. `alert:PaymentsApiErrorBudgetBurn:threshold` became `alert:PaymentsApiErrorBudgetBurn:0.05`. Five of seven findings on the first live page came back with nothing usable, all for this reason.

**Whose bug this is.** Mine, mostly — but it is worth writing down because the mistake is easy and the symptom is misleading. A subject like `alert:X:threshold` is a machine identifier that reads as prose containing the exact word the instruction is about, so putting it in the document offers a plausible wrong thing to correct. The symptom looks like the model declining to help.

**Worked around.** The heading is now `Passage 1` and nothing else; the subject travels in the instruction, which is keyed by passage number anyway. Fixed rate went from 2/7 to 4/5 on the same page, with the fifth correctly declined (a dead dashboard link has no correct replacement).

---

## 11. "Do not add commentary" is followed most of the time, and the exceptions are plausible prose

**What I did.** Instruction says, verbatim: *make the smallest edit that corrects the fact… do not add commentary*.

**What happened.** Usually obeyed. Sometimes not:

```
'Payments Platform'   -> 'Payments Platform is not a valid rota; valid rotas are
                          Fulfilment, Payments Core, and Tracking.'
'rollback-production' -> "rollback-production (Note: 'rollback-production' is not a
                          valid CI job; please use one of the declared jobs: …)"
```

Both are *correct and helpful*, and both would have been spliced into the middle of a sentence in an operational runbook.

**How badly it blocked.** It did not block, it nearly shipped. The guard is `edit._sane`: a replacement that still contains the value it was meant to replace has appended commentary rather than replaced anything, and one much longer than what it replaces is prose. Refusing escalates the finding to a human, which costs one look; accepting costs a paragraph of model prose inside an incident instruction.

---

## 12. Run-to-run variance on an identical request is large enough to plan for

**What I did.** Sent the same batch of five passages three times.

**What happened.** Usable replacements came back for 1/5, then 4/5, then 4/5 — same document, same instruction, same model tier.

**How badly it blocked.** Not at all, once noticed, but it would have been badly misleading as a one-shot measurement: a single run would have supported either "this works" or "this barely works" depending on which one you did.

**Worked around, and it falls out of the design.** `propose_all` skips findings that already carry wording, so re-running retries only what failed and costs one operation per page that still needs one. Two retries converged. Worth stating plainly in any measurement of this layer: **the deterministic half of this project is deterministic and the wording half is not**, and the register is what makes the difference survivable — a finding with no usable wording escalates to a human rather than being written wrongly.

---

## 13. A scoped token can create a page but not delete one

**What I did.** `DELETE /wiki/api/v2/pages/{id}`, to clean up the page `seed.py` had just created.

**What I expected.** `204`. Creating had worked, and a token that can create and overwrite a page can already destroy its content.

**What happened.** `401 Unauthorized; scope does not match`. `delete:page:confluence` is not among the scopes an API token can be granted, so the demo can plant a page and cannot remove it.

**How badly it blocked.** Barely, but it caused a worse bug than itself. `seed.py delete` printed `delete 557058 -> 401` and returned normally, so `./demo` announced *"walkthrough complete, and every stage passed"* with the page still sitting in the space. Reporting success for something that did not happen is the exact failure this project exists to catch, and it was in the cleanup path of its own demo. It now exits non-zero and prints what to click.

**Worth noting for the threat model.** A token that can rewrite a page's entire body but cannot delete it is a slightly odd security boundary — the damage a compromised token could do is bounded by version history either way, and version history is what actually protects you.

---

## 14. An open editor tab silently reverts API writes, and version numbers do not stop it

**Verified by losing a page to it.**

**What I did.** Ran the live write round-trip against page 98311, which appends a marker, reads it back, restores the original body and asserts byte-identity. It passed. The page was correct, at version 5, 5,653 bytes.

**What happened.** Nineteen minutes later the page was 29 bytes — a single empty paragraph. Version history:

```
v6  18:06  message: "Autosaved"                                    <- the browser
v5  17:47  message: "runbook-reconciler: approved fix to one passage"
v4  17:47  message: "runbook-reconciler: approved fix to one passage"
v1  22:01  (original)
```

The page had been **open in the Confluence web editor** in another tab the whole time. The editor holds its own copy of the document from when it was opened, does not notice writes that arrive through the API, and autosaves its stale copy over the top whenever it feels like it.

**Why the version check did not save it.** Optimistic concurrency protects *this tool* from overwriting somebody else — our `PUT` carries the version we read and fails if it moved. It does nothing in the other direction: the editor's autosave is a perfectly valid write of a new version, and Confluence does not merge or warn.

**How badly it blocked.** It cost a page, recovered from version history, and it is the most important limitation in this file. Nothing in the API surfaces "a human has this page open", so the tool cannot detect it, refuse, or warn. The honest mitigations are operational: sweep when people are not editing, keep the review gate so writes are deliberate and few, and rely on version history — every change this tool makes is one labelled version that can be reverted in two clicks.

**How to reproduce.** Open a page in the Confluence editor, leave the tab open, write to the same page through the API, then wait for or trigger an autosave. The API write is gone.

---

## Things this file does not claim

Both live paths **have** now been run, on 2026-08-15, and items 7, 8 and 9 above
are what they found. Reproduce them with:

```bash
RR_LIVE_SUPERDOCS=1 ./rr test tests/test_edit_live.py                    # 1 operation
RR_LIVE_CONFLUENCE_TESTS=1 RR_LIVE_PAGE_ID=<a page you own> ./rr test -k live
```

The **full loop has now run against live Confluence**, on 2026-08-15: a seeded
runbook page (`seed.py`) with seven planted contradictions, swept live,
worded through SuperDocs, approved, and written back — leaving exactly four
minimal changed ranges on the page and every other byte identical:

    replace: '2' -> '5'        (error budget 0.02 -> 0.05)
    replace: '750m' -> '1.2'   (latency 750ms -> 1.2s)
    replace: '4' -> '6'        (replicas)
    replace: '7' -> '14'       (backup retention days)

What is still **not** claimed:
- **The measured precision and recall are against a synthetic corpus** of 8
  runbooks, and were produced by the deterministic layer only — no live call is
  involved in that number, by design.
- **`rr watch` has not been run against a live Confluence space for long
  enough to observe the self-trigger case.** The version ledger that prevents it
  is unit-tested; the loop it prevents has not been provoked in production.

Stated because a capability honestly absent beats one claimed and broken, and
because "tested against a stub" and "tested against the service" are different
sentences — item 7 is exactly what the difference costs.
