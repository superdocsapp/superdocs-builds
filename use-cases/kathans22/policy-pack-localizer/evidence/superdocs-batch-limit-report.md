# Bug report: multi-section `chat` edits are unreliable, and the response text does not reflect what actually happened to the document

Filed against: SuperDocs `chat` tool (MCP), synchronous, default `approval_mode` (`approve_all`).
Found while building: `use-cases/kathans22/policy-pack-localizer` (Task 2, Build 1).
Severity: blocking for the design as originally planned; **not blocking for the shipped
build** — we changed the design to detect and route around it (see "What we did about it").
Not marked urgent for that reason.

## What broke

A `chat` call that edits several sections of a document in one request cannot be trusted to
either (a) edit all of them, or (b) tell you truthfully which ones it actually edited. Four
distinct symptoms were observed, using the same document and the same kind of instruction
(replace specific paragraph(s) with given text, annex-only, core sections never named):

1. **A batch of 4 sections reports full success and changes zero sections.**
   Response: `"I went through 4 section(s) but nothing actually changed... 4 section(s)
   couldn't be updated."` The document is byte-identical before and after. Reproduced twice,
   with two structurally different instruction phrasings (see Repro A and B below).

2. **A batch of 2 sections reports partial success and silently drops one section — with no
   error, no warning, and no indication in the summary that anything is missing.**
   Response: `"1 section edited, rest untouched"` — but the response's own `changes_summary`
   gives no reason to suspect the *other* named section didn't land. Only re-exporting and
   diffing against the pre-edit text reveals it. Reproduced multiple times, on batches that
   had *previously* worked in the same session.

3. **A batch of 4 sections reports partial success (1 of 4) while naming *different* sections
   as "couldn't be updated" than what was actually requested**, and this compounds: retrying
   a single section by itself, on a session that had just experienced symptom 2, returned the
   same "couldn't be updated" message for *two* sections — one of which was never part of that
   request. The session appears to enter a state where subsequent single-section requests keep
   failing or get misattributed to the wrong content, independent of batch size. Recovered
   only after multiple retries in that session, or by moving to a fresh session.

4. **A distinct transient error, also billed**: one call returned only
   `"I encountered an issue. Please try again."` — no document_changes, no explanation —
   and `usage.was_billable: true, ops_charged: 1`.

Sections 1–3 individually were each edited successfully, reliably, when sent as the only
target in their own call. 2 sections and 3 sections in one call also succeeded cleanly in
several trials — but not in all trials (see symptom 2), so **no batch size above 1 is safe to
assume reliable**, even ones observed to work.

## What we expected

Given the tool's own documentation ("Synchronous AI chat that can rewrite specific
paragraphs... add or remove table rows, restructure sections") and the batching pattern it
invites (`response_mode='compact'` returning per-section `chunk_diffs`), we expected: a
multi-section edit either applies all named sections and says so accurately, or reports
exactly which ones failed and why — not a response whose plain-language summary is
disconnected from the document's actual state.

## What we got — repro

**Document:** the project's `config/policy-master.md` (9 sections, ~1,000 words), uploaded via
`upload_document_base64`, unmodified between attempts within one session.

**Repro A — 4-section batch, label-style instruction (first attempt, billed 1 op, changed 0
sections):**
```
Localise this policy for India (Mumbai Office), writing all replaced text in English. Replace
each of the following annex sections independently with the content given for it. Do not add,
remove, or reword anything outside these sections; every other section must be left exactly
as it is.

Section 6 "Reporting Channels": internal contact reachable at safeguarding.in@meridian-relief.example or +91 22 0000 0000; external channels are Childline India (1098 — toll-free 24-hour child helpline); Police Control Room (112)
Section 7 "Applicable Law": Protection of Children from Sexual Offences (POCSO) Act, 2012; Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013; Juvenile Justice (Care and Protection of Children) Act, 2015
Section 8 "Escalation and Response": tier 1 — Country Safeguarding Focal Point, Mumbai — 24 hours; tier 2 — Regional Director, South Asia — 72 hours; tier 3 — Director of Safeguarding, headquarters — 7 days; regulator notification — National Commission for Protection of Child Rights (NCPCR)
Section 9 "Acknowledgement": office 'Mumbai Office' in 'India', safeguarding lead 'Priya Nair', with blank fields for recipient name, role, date, and signature
```
Response: `"I went through 4 section(s) but nothing actually changed..."`, `usage.ops_charged: 1`.
Retrying this exact message twice more (same session) returned the same failure, both times
with `usage.was_billable: false`.

**Repro B — 4-section batch, explicit-imperative-per-section instruction (different wording,
same result, not billed on this attempt):**
```
Replace only the following four sections in this policy, leaving every other section exactly
as it is. For each one, replace its current content entirely with the text given.

Replace the contents of section 6 (Reporting Channels) with: internal contact reachable at safeguarding.in@meridian-relief.example or +91 22 0000 0000; external channels are Childline India (1098 — toll-free 24-hour child helpline) and Police Control Room (112).

Replace the contents of section 7 (Applicable Law) with: Protection of Children from Sexual Offences (POCSO) Act, 2012; Sexual Harassment of Women at Workplace (Prevention, Prohibition and Redressal) Act, 2013; Juvenile Justice (Care and Protection of Children) Act, 2015.

Replace the contents of section 8 (Escalation and Response) with: tier 1 — Country Safeguarding Focal Point, Mumbai — 24 hours; tier 2 — Regional Director, South Asia — 72 hours; tier 3 — Director of Safeguarding, headquarters — 7 days; regulator notification — National Commission for Protection of Child Rights (NCPCR).

Replace the contents of section 9 (Acknowledgement) with: office 'Mumbai Office' in 'India', safeguarding lead 'Priya Nair', with blank fields for recipient name, role, date, and signature.
```
Same failure, byte-identical result. This rules out instruction phrasing as the cause.

**Boundary, precisely pinned (each on a fresh session, same instruction style as Repro A,
scoped to N sections):**

| Sections in one call | Result |
|---|---|
| 1 | succeeds (repeated across multiple unrelated sessions) |
| 2 | succeeds in some sessions; silently drops one section in others (symptom 2) |
| 3 | succeeded once, cleanly, in the one trial run |
| 4 | fails every time tried (2 phrasings, 1 session; consistent) |

We deliberately did not keep pushing to find where "3 always works" might also fail
intermittently — the point of pinning "works at 3, fails at 4" was to make the report
precise, not to find a safe number to hardcode (see "What we did about it").

## Billing check

We checked whether a batch that reports success and changes nothing is billed, per this
report's own standard of "verify the count before and after," not just repeat the docs.

- The **first-ever** attempt at a novel 4-section instruction: `was_billable: true,
  ops_charged: 1` — billed, despite zero document changes.
- **Identical retries** of that same failing instruction, in the same session: `was_billable:
  false, ops_charged: 0` — not billed.
- The **transient "I encountered an issue"** error (symptom 4): `was_billable: true,
  ops_charged: 1` — billed, despite returning no result at all.
- Separately, we also confirmed a **preview-only** call (`approval_mode='ask_every_time'`,
  nothing applied) is never billed — that part matches sensible expectations and is not part
  of this bug.

So: a *novel* failing batch is billed once; a *repeated identical* failing batch is not billed
again; a bare error is billed. None of this is stated in the docs we found.

## How badly this blocked us

Fully blocking for the original design: CLAUDE.md's economics assumed one chat call could
replace all 4 annex sections reliably, for 1 operation per pack. That assumption does not
hold. We could not ship the "core hash proven to match the lock" checkpoint until we stopped
trusting the response and started verifying the document directly.

## What we did about it (not part of the bug — context for why this isn't marked urgent)

We did not hardcode "batches of 4 fail" or "batches of 3 are safe" anywhere — an undocumented
boundary on a live API is exactly the kind of special-casing that breaks again the next time
the boundary moves. Instead:

- `annex_batch_size` is now an explicit, required `config/manifest.yaml` field (currently 2),
  not a code constant — adjustable without a code change as this is re-verified over time.
- After every batch `chat` call, we re-export the document and check whether each targeted
  section's text actually changed from the master's original — independent of what the
  response claims.
- Any section that did not land gets its batch split (bisected) and retried at a smaller size,
  bounded, rather than trusting a retried identical request to somehow work (symptom 1 proved
  it usually doesn't) or trusting the response text to say what failed (symptom 2/3 proved it
  can be wrong or silent).
- A section that still will not land after being isolated to a batch of one is left for our
  own core/annex verification step to catch and quarantine the pack — it is never shipped
  silently incomplete.

Full detail and code references: `use-cases/kathans22/policy-pack-localizer/PROGRESS.md`.
