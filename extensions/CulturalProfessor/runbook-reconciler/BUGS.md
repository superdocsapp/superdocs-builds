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

## 2. The v1 REST API is entirely unreachable with a scoped token, which takes CQL search with it

**What I did.** Called `GET /wiki/rest/api/content/search?cql=label="runbook"`
through the working gateway host, to find every page carrying a label in one
request.

**What I expected.** `200` and a result set. CQL search is how the Confluence
documentation tells you to do this, and there is no v2 equivalent.

**What happened.** `401 Unauthorized; scope does not match`, through the gateway
that serves v2 successfully in the same session with the same header. Every v1
path behaves this way. The v2 paths this build needs — `pages`,
`pages/{id}/labels`, `labels`, `spaces` — all work.

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

## Things this file does not claim

**The SuperDocs edit path has not been run against the live API by this build.**
Everything in `reconciler/edit.py` is verified against `tests/stub_superdocs.py`
— an in-process stand-in, written from the sibling build's live experience. That
proves the batching, the change-to-finding mapping and the approval handling;
it is not evidence that `api.superdocs.app` behaves that way today.
`tests/test_edit_live.py` is the opt-in test that would establish it and costs
one paid operation:

```bash
RR_LIVE_SUPERDOCS=1 ./rr test tests/test_edit_live.py
```

**No live Confluence *write* has been performed by this build either.** Reads
are exercised freely; the write round-trip is gated behind
`RR_LIVE_CONFLUENCE_TESTS=1` and `RR_LIVE_PAGE_ID`, and has not been run against
a page anybody cares about.

Both are stated because a capability honestly absent beats one claimed and
broken, and because "tested against a stub" and "tested against the service" are
different sentences.
