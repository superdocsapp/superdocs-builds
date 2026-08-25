# Verification

ServiceNow is the system of record. When an LLM rewrites a document built from a
ServiceNow change, certain values in it are not the model's to change.

This document is the specification of that guarantee: what is protected, what is checked,
what has actually gone wrong, and what the gate does not cover.

## What is protected

| Class | Fields | If the model changes it |
| --- | --- | --- |
| **Preserved** | `configuration_item`, `work_notes` | **Blocked.** Must appear character for character in the exported document. |
| **Advisory** | `number`, `resolution_code`, `status` | **Flagged.** ServiceNow-owned, but a reviewer may accept a rewrite. |

Defined in `documentMapping.js` as `PRESERVED_FIELDS` and `ADVISORY_FIELDS`. Adding a field
to either list is the whole change.

Before any of this runs, `REQUIRED_FIELDS` validation rejects an incomplete record outright
— `CHG0010054` in the fixtures exists to exercise that path. Nothing incomplete reaches
SuperDocs.

## The five gates

A run passes through the gate five times. Any one of them can stop it.

| # | When | Check | On failure |
| --- | --- | --- | --- |
| 1 | Before upload | Record has every required field | `422`, nothing sent to SuperDocs |
| 2 | Per proposed edit | `verifyProposedChange` | Verdict shown to the reviewer |
| 3 | On approve of an edit | Re-verified from the server's own copy | `409` if blocked, whatever the client asked |
| 4 | Before sign-off | `verifyPreservedValues` on the finished document | `409`, approval refused |
| 5 | Before export | `verifyPreservedValues` again | `409`, export refused |

Gate 5 is not redundant. Approval is a point in time; the document can move after it.

## The three rules

Applied to each proposed chunk, comparing the text it replaces (`before`) with the text it
proposes (`after`). Comparison is whitespace-insensitive — rewrapping a paragraph is not a
value change.

### Rule 1 — Removal

The chunk being replaced carried a protected value and the replacement does not.

> *Configuration item was changed. ServiceNow value: "PROD-API-GATEWAY-01".*

**Blocking** for preserved fields.

### Rule 2 — Mislabelled restatement

The new text labels a field and gives it different text. `Configuration Item: …`,
`Work Notes: …`, and the other labels in `FIELD_LABELS`.

The label has to read as a label — followed by a separator, or ending its own line or table
cell. Without that constraint, prose like "Status was preserved by draining traffic" reads
as a restatement of the Status field and every rewrite trips.

**Blocking** for preserved fields, **advisory** otherwise.

When both sides are long, the finding quotes them from the point where they actually
diverge rather than from the start — two strings truncated to the same length look
identical even when they differ later, which makes for a useless finding.

### Rule 3 — Paraphrase in added prose

Prose of substance (≥ 80 characters) that mentions a preserved field by name but never
quotes its value.

> *New text discusses the configuration item without quoting the ServiceNow value
> "PROD-API-GATEWAY-01".*

**Advisory only**, and only for preserved fields. The canonical section still carries the
verbatim value, so the document survives gate 5 — but the reviewer should know the summary
is talking around a value rather than citing it. An advisory field being discussed in prose
("resolution was reached without customer impact") is ordinary writing, not drift.

### Verdicts

| Verdict | Meaning | Reviewer |
| --- | --- | --- |
| `blocked` | Any blocking finding | Cannot approve. The server refuses. |
| `advisory` | Findings, none blocking | Their call |
| `safe` | No findings | Approve |

A rejection is sent back to SuperDocs with the reason attached, so the retry is informed.

## What this has actually caught

Not hypotheticals. All three came out of live runs against `api.superdocs.app`.

**1. A rewritten configuration item.** Asked for a summary block, the model wrote
`API-GW-PROD-01` where ServiceNow says `PROD-API-GATEWAY-01`. Caught by rule 2. Blocked.

**2. A reworded resolution code.** `Successful` became a sentence. Caught by rule 2 as
advisory — `resolution_code` is ServiceNow-owned but not export-blocking.

**3. A paraphrased configuration item.** Asked for an executive summary, the model wrote
*"the configuration item identified as the production API gateway"* — never quoting the
value. Nothing was removed and nothing was restated under a label, so rules 1 and 2 stayed
silent and **the change was rated safe**. Rule 3 exists because of this run.

Notably, the model corrected itself one batch later, writing
`(Configuration Item: PROD-API-GATEWAY-01)` verbatim. The gate has to hold for the batch
where it does not.

## Two bugs the gate had

Documented because a verification layer that is wrong is worse than one that is absent.

**A heading was rated `blocked`.** A proposed `<h2>Configuration Item</h2>` — a label with
nothing after it — read as "the label says the value is empty". The server refuses to
approve a blocked change, so that was a chunk the reviewer could only ever reject, with no
way forward. A label with nothing after it is a heading, not a claim. Deletion is still
caught, because rule 1 fires when the value was in the chunk being replaced.

**Rule 3 was too broad.** Applied to advisory fields it flagged ordinary prose — any
sentence containing the word "resolution" or "status". Restricted to preserved fields.

Both are regression-tested.

## After export

The exported document's checksum (`sha256`, first 16 hex characters, computed on
whitespace-normalized text) is recorded in the audit trail and written back to the
ServiceNow change as a work note, alongside the session id and who approved it:

```
Production change record generated and exported.
Document: chg0010053-production-change-record.docx
Checksum (sha256/16): 459756ffa5c17e00
SuperDocs session: svcflow-chg0010053-mt5kxahx
Approved: 2026-08-23T09:10:42.045Z by Hannah Brooks
Verified verbatim: Configuration item, Work notes
Source record: CHG0010053
```

ServiceNow journal fields append rather than overwrite, so this adds to the record's
history without editing it.

## What the gate does not cover

Stated plainly, because the guarantee is only worth what its boundaries are.

- **It is literal, not semantic.** It checks that a string survives. A rewrite that
  preserves `PROD-API-GATEWAY-01` while inverting the meaning of the sentence around it
  passes.
- **It protects values, not claims.** The model can invent a rollback plan that is wrong
  as long as it does not touch a protected field. The edit instruction asks it not to
  invent facts; nothing enforces that.
- **Advisory findings are not enforced.** By design — but that means a reviewer clicking
  through can approve a reworded resolution code.
- **Reviewer identity is self-asserted.** The name in the audit trail is typed, not
  authenticated. See [Operations § Limits](OPERATIONS.md#limits).
- **New sections are unconstrained.** A chunk that mentions no protected field is `safe`
  by definition, however much prose it adds.
