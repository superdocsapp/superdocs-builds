# Findings

Divergences between what SuperDocs publishes and what it does, found while building this
mock. Each is verified against the live service before it is reported; anything still
unverified is marked **VERIFY** and is not claimed anywhere else in this repository.

Confirmed findings go to `hello@superdocs.app` in the shape the round asks for: what I did,
what I expected, what happened instead, how badly it blocked me, and a repro.

Nothing here is a criticism of the product. A mock exists precisely to pin down these edges,
and finding them is the job working as intended. Every one of these was surfaced by the
approach itself — recording against the live service and validating the result against the
published spec — rather than by reading carefully.

| | Finding | Status | Severity |
|---|---|---|---|
| F-001 | `whoami` omits the promo bucket, under-reporting spendable quota | confirmed | medium |
| F-002 | Export `200` is a binary download; `openapi.json` declares `application/json` | confirmed | medium |
| F-003 | Upload format support contradicts across two docs pages and the live service | confirmed | medium |
| F-004 | The primary upload routes publish an empty `200` schema (**earlier high-severity claim retracted**) | confirmed | low-medium |
| F-005 | Legacy `.doc` returns `400`, not the documented `415`, and conversion is down | confirmed | medium |
| F-006 | Duplicate SSE `sequence` numbers can lose the `final` event on resume | confirmed | **high** |

---

## F-006 — Duplicate SSE `sequence` numbers can make a resuming client miss `final`

**Status:** confirmed live, 2026-08-10 · **Severity:** high · **Blocked me:** no

**What I did.** Recorded the SSE stream of a review-mode job through to completion, then
read the `sequence` field off every frame.

**What I expected.** `/guides/streaming` states it twice: *"Every event carries a
monotonically increasing `sequence` number"*, and *"reconnect with the `last_sequence` query
parameter set to the highest sequence you already processed — the stream replays **only
newer** events."*

**What happened.** The tail of the stream was:

```
seq= 8   intermediate           🔄 Processing 2 sections in parallel...
seq= 9   proposed_change_batch  {"type": "batch_approval", ...}
seq=11   intermediate           ✅ Successfully updated all 2 sections.
seq=11   final                  ✅ Successfully updated all 2 sections. - edit: ...
```

`sequence` **11 is emitted twice** — once on an `intermediate` and again on the `final` —
and `10` is skipped. The series is therefore not strictly increasing.

**Why it matters.** The duplicate breaks the documented resume contract, and it breaks it at
the worst possible frame. A client does exactly what the guide says: processes the
`intermediate`, stores `last_sequence = 11`, and then its `EventSource` drops — routine on
mobile, on a laptop lid closing, behind a proxy with an idle timeout. It reconnects with
`last_sequence=11`. The `final` event is not *newer* than 11, so it is never replayed. The
job has completed and the document has changed, but the client sits waiting for a completion
that will never arrive, with no error to react to.

The skipped `10` is harmless on its own — monotonic does not mean contiguous — but the two
together suggest a counter incremented on paths that do not always emit, or two emitters
sharing one counter.

**Repro.** `cassettes/proposed-change-batch.json`, the second recorded stream (the one with
`last_sequence` set). The frames and their sequence numbers are stored verbatim.

**Suggested shape.** Allocate `sequence` from a single monotonic source at emit time, and
add a contract test asserting strict increase across a full job — it is a one-line invariant
and it protects a documented guarantee that clients are told to rely on.

---

## F-004 — the primary upload routes publish an empty response schema

**Status:** confirmed live, 2026-08-10 · **Severity:** low–medium · **Blocked me:** no

> **Retraction.** An earlier version of this finding claimed that
> `POST /v1/documents/upload` violates `ProcessDocumentResponse` by omitting the required
> `status` and `parse_mode`, and rated it high severity. **That was wrong.** The upload
> route does not reference `ProcessDocumentResponse` at all — its `200` schema is `{}`. The
> route that *does* reference it, `POST /v1/uploads/{upload_id}/process`, was then driven
> end to end (pre-signed upload, PUT, process) and **conforms exactly**: `status:
> "completed"`, `parse_mode: "document"`, every declared field present. I had matched a
> schema to a route on the strength of its field names. The mistake is left visible here
> because a findings list that quietly edits itself is not worth reading.

**What remains, and it is real but much smaller.** Both multipart upload routes publish an
empty success schema:

| Route | `200` schema |
|---|---|
| `POST /v1/documents/upload` | `{}` |
| `POST /v1/documents/upload-base64` | `{}` |
| `POST /v1/uploads/{upload_id}/process` | `ProcessDocumentResponse` ✓ |

An empty schema validates anything, so the spec says nothing about the shape integrators
actually consume from the endpoint most of them start with — `html`, `chunks_count`,
`version_id`, `page_setup`, `documents`, `document_id`, `persisted`. A generated client
types this as `Any` and the developer goes back to reading prose.

**Why it is worth fixing anyway.** `ProcessDocumentResponse` already describes nearly this
shape and is already maintained. Pointing the two upload routes at it — with `document_id`,
`documents` and `persisted` added, and `status`/`parse_mode` relaxed to optional since the
multipart route does not send them — would cost one edit and give three endpoints one
documented contract.

---

## F-001 — `whoami` under-reports available quota by omitting the promo bucket

**Status:** confirmed live, 2026-08-10 · **Severity:** medium · **Blocked me:** no

**What I did**

```
GET /v1/agents/whoami        →  {"tier":"free","quota":{"monthly_limit":500,
                                 "used":0,"remaining":500,...}}
GET /v1/users/me/promotions  →  {"active":[{"name":"Round 2 Builders - August 2026",
                                 "ops_granted":10000,"ops_remaining":10000,...}]}
```

**What I expected.** `whoami` is the account-status call an agent is told to budget from —
the MCP reference calls `get_account_status` "the cheapest way to budget a long job", and the
rate-limits page routes API-key callers to it because `/v1/users/me/usage` is web-app-only
(that rejection is correct and clearly worded, incidentally). So I expected its `quota` to
reflect everything the account can actually spend.

**What happened.** It reports the tier bucket only. An account holding 10,000 promotional
operations reads as `remaining: 500` — a 21× under-count here. `UsageInfo` already models the
distinction (`bucket_used: "tier" | "promo"`, `redemption_id`), so the concept exists on the
response side; it just is not surfaced on the status side.

**Why it matters.** An autonomous agent following the documented guidance would ration or
refuse work it has ample quota for — the exact failure the "budget your operations" advice
exists to prevent. It bites hardest for the Round 2 builders holding a promo code, which is
how I hit it.

**Suggested shape.** Add the promo bucket to `AgentQuota` — `{"tier": {...}, "promo": {...},
"total_remaining": N}` — or at minimum a `promo_remaining` field agents can sum.

**Supporting evidence found later.** The `usage` block on a completed chat job carries the
promo bucket in full:

```json
{"bucket_used": "promo", "ops_charged": 1, "monthly_used": 0, "monthly_limit": 500,
 "monthly_remaining": 500, "subscription_tier": "free", "quota_exhausted": false,
 "promotions": [{"name": "…", "ops_granted": 10000, "ops_remaining": 9998,
                 "expires_at": "2026-09-09T…"}]}
```

So the data is already assembled and already shipped on the chat path — it simply is not on
the status path that agents are pointed at. That makes this a plumbing gap rather than a
missing feature, which is the cheap kind to close. (Note also that `promotions[]` here is not
described by the `UsageInfo` schema in `openapi.json`.)

---

## F-002 — Export returns a binary download; the spec declares JSON

**Status:** confirmed live, 2026-08-10 · **Severity:** medium · **Blocked me:** no

**What I did.** `POST /v1/documents/export` with `{"session_id": ..., "format": "docx"}`.

**What I expected.** The pinned `openapi.json` declares the `200` on this route as
`application/json`.

**What happened.** A genuine binary DOCX:

```
content-type        : application/vnd.openxmlformats-officedocument.wordprocessingml.document
content-disposition : attachment; filename="agreement-export.docx";
                      filename*=UTF-8''agreement-export.docx
body                : b'PK\x03\x04...'          (ZIP magic — a real .docx)
```

`/concepts/documents` describes exactly this and every example writes `response.content`
straight to a file, so **the prose docs are right and the spec is wrong**.

**Why it matters.** A generated client types this route as returning JSON. Some will attempt
`response.json()` on ZIP bytes and fail with a decode error that points nowhere near the
cause. The out-of-enum `format` case behaves correctly, returning the documented `422`.

**Suggested shape.** Declare the `200` as `application/octet-stream` (or the per-format media
types) with `format: binary`, and document `X-Export-Warnings` in the spec alongside it.

---

## F-003 — Upload format support disagrees three ways

**Status:** confirmed live, 2026-08-10 · **Severity:** medium · **Blocked me:** no

Three sources, three different answers:

| Source | `.doc` | `.odt` | `.tex` |
|---|---|---|---|
| `/concepts/documents` "Supported formats" | listed | **listed** | absent |
| `/errors/error-codes` `415` message | "unsupported" | absent | absent |
| Live `supported_formats` in a `413` body | absent | absent | **listed** |
| Live behaviour on upload | `400` (see F-005) | **`200`, parsed fine** | not tested |

So: `.odt` uploads successfully and is parsed into chunks, yet appears in neither the live
service's own advertised list nor the `415` message. `.tex` appears in the live list and in
no documentation page. `.doc` is listed as supported on one page and unsupported on another.

**One more, smaller:** the `.odt` upload came back with `page_setup.source: "docx"`. The
geometry is plausible, but the provenance label is wrong for an OpenDocument source.

**Why it matters.** An integrator building a file picker from the docs ships the wrong
`accept` list in either direction — rejecting files the service handles, or offering files it
refuses.

**Suggested shape.** Generate the docs' supported-format list from the same constant the
`413` body and the `415` message use, so the three cannot drift again.

---

## F-005 — Legacy `.doc` returns `400` where the docs promise `415`, and conversion is down

**Status:** confirmed live, 2026-08-10 (two attempts, 13.8 s then 0.9 s) · **Severity:**
medium · **Blocked me:** no

**What I did.** Uploaded a file with a `.doc` extension carrying OLE2 magic bytes, twice,
several minutes apart.

**What I expected.** Per `/errors/error-codes`, a `415`:

```json
{"detail": "Unsupported file type: .doc. Supported types: .pdf, .docx, .txt, .rtf, .md, .html, .htm"}
```

**What happened.** Both times, a `400`:

```json
{"detail": "We temporarily can't convert legacy .doc files (the document-conversion service
is warming up). Please try again shortly, or save 'legacy-format-probe.doc' as .docx and
re-upload."}
```

Two things follow. First, the message implies `.doc` **is** meant to be supported through a
conversion service — which matches `/concepts/documents` and contradicts the `415`
documentation. Second, that conversion service appears to be genuinely unavailable rather
than warming: the second attempt returned in 0.9 s, so this is not cold-start latency.

**Why it matters.** `/errors/error-codes` explicitly tells integrators to "catch `415`
(Unsupported Media Type) separately from `400` when handling upload-validation failures". An
integrator who follows that advice routes this response into their generic bad-request
branch and shows the user the wrong message. And a caller cannot distinguish "this format is
never supported" from "this format is supported but the converter is down right now" — those
need different retry behaviour, and both arrive as a bare `400`.

**Suggested shape.** A distinct status or an `error_code` for a degraded-dependency refusal,
so `retryable` is machine-readable — the typed-error-taxonomy idea from the open task list
would cover this cleanly.

---

## N-1 — a caution, not a defect: query-string auth lands in logs

SSE authenticates with `?api_key=…` because `EventSource` cannot send headers (B-004).
That is forced by the browser API, not a choice, and there is no obvious alternative short
of a short-lived stream token.

It is worth writing down anyway, because the consequence is easy to miss: the key ends up
in **client logs** (httpx logs every request URL at INFO, and that is how I noticed —
a hardening test of my own caught the test client, not the mock), in **proxy and CDN access
logs**, in **browser history**, and potentially in a **`Referer`** header. None of that is
under SuperDocs' control once the URL is built.

Two things would help integrators without changing the protocol: a line in
`/guides/streaming` naming the hazard, and a note that keys used for browser-side streaming
should be treated as more exposed than server-side ones and rotated accordingly. A
short-lived, stream-scoped token minted per job would remove it entirely, if it is ever
worth the endpoint.

Filed as an observation rather than a bug: nothing here is behaving incorrectly.

---

## Confirmations, not findings

Worth recording that these matched their documentation exactly on the live service, because
the contract suite asserts them and a reader should know which claims are load-bearing:

- `proposed_change_batch.content` **is** a JSON-encoded string requiring a second parse,
  while `final.result` is a parsed object (B-052). The single most-warned-about trap in the
  integration docs is real and reproducible.
- An approve body carrying `changes` but no top-level `approved` **is** rejected `422`, with
  `loc: ["body","approved"], type: "missing"` (B-041).
- The SSE event order on a review turn was exactly `document_sync` → `intermediate`×4 →
  `proposed_change_batch` (B-058, B-051).
- The `413 DOCUMENT_TOO_COMPLEX` body is fully structured — `limit_expandable: true`,
  `section_count: 25602`, `max_sections: 25000`, `contact_email`, plus a `request_increase`
  block carrying an `agent_hint` and the exact endpoint and MCP tool to call. This is the
  best-designed error body on the surface and deserves saying so.
- `/v1/users/me/usage` rejects `sk_` keys with a clear, actionable `401` (B-005).

One observation for the ledger rather than the inbox: on a HITL review pause,
`metadata.awaiting_kind` is **absent** rather than set to a review-specific value. That
matches the docs' "otherwise" wording, but integration code must treat *absence* as the
review branch, not merely a value other than `continue_prompt`.
