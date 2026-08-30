# Demo Guide — 7 minutes

A concrete walkthrough script for showing this build to a founder. Every value below is
real, seeded data — nothing needs to be faked live. Start at the Dashboard.

## 0. Set the frame (30s)

> "SuperDocs doesn't ask *where's the document*. It asks: what does it claim, why should
> I trust that, what rules does it satisfy, what changed, what's risky, and what should
> happen next. This workspace has six real documents at different points in that
> lifecycle — one of them, a vendor contract, is genuinely messy and mid-negotiation,
> which is where the product proves itself."

Point at the Dashboard: 8 metrics, an attention feed sorted by severity, a
documents-at-a-glance list, recent decisions. **"What needs my attention"**, not a
generic analytics page.

## 1. Open the document → inspect Reality (60s)

Click into **Master Services Agreement — Ironclad Cloud Services** (status: *In
Review*, v3.2).

The Reality tab is four instrument readouts, not a KPI wall: **Confidence**,
**Compliance**, **Evidence Coverage**, and **Risk** (High, score 20) — each one a
calculated number, not a hand-set flag. Below it, "Why this risk level" is already
broken into named factors: *2 High-Impact Changes, 2 Unsupported Claims, 2 Stale
Evidence Sources, ...* — every factor links straight into the Risk tab.

## 2. Inspect claims, trace evidence (90s)

Switch to **Claims & Evidence**. Left side is the actual contract text — Section 2's
uptime commitment, Section 3's security clauses, Section 4's data-residency language.
Right side is every claim the document makes, sorted worst-first.

Click the claim: *"Vendor guarantees a Monthly Uptime Percentage of 99.95%..."* — marked
**Contradicted**. The drawer opens the **Provenance Thread**: Claim → Evidence
(*Trailing 6-Month Uptime Report*) → Source (*Ironclad Status History Export*) →
Verification (*Darius Cole contradicted it on Jul 5*). The contradiction note is right
there: actual measured uptime is 99.91%, not 99.95%.

Now open *"Vendor shall not engage a new Subprocessor without 30 days' notice"* —
**Unverified**, and the thread shows a **broken link**: a dashed, hollow node reading
*"No evidence attached."* That's the same visual grammar as the solid nodes above it —
missing evidence looks structurally different from missing-and-hidden.

## 3. Identify risk (45s)

Switch to **Risk**. Score 20, four factors, each with a real count and a plain-English
label — *"2 recent high-impact changes," "2 unsupported claims"*, etc. Below that,
**Recommended actions** — this is the AI-extension seam actually running live (an
`async` call to the mock intelligence service), not a static list.

## 4. Inspect requirements — the "why," not just the score (45s)

Switch to **Requirements**: 67% compliance, grouped by category. Point at the two
**Failed** items in *Policy*: **"Vendor accepts Company Incident Response Policy
(IR-002) notification window"** — failed, with the explanation stated inline: the
contract commits to 72 hours, company policy requires 24. Not a bare red X — a sentence
a lawyer can act on.

## 5. Review a change (45s)

Switch to **Changes**. The v3.1 → v3.2 entry: *"12 text changes, 2 claim changes, 1
requirement affected, 1 evidence relationship changed, 1 risk increased."* The
highlight bullets underneath say exactly what: the liability cap moved from 1.0× to
1.5× trailing fees, without a re-review. That's the differentiator over a line diff —
this is "what actually changed," at the level a reviewer thinks in.

## 6. Take an action, verify the result (60s)

Back on **Risk**, click **Mark resolved** on *"SOC 2 Type II report is 14 months old."*
Watch the risk score visibly drop and the factor disappear from the list — live, no
page reload.

Switch to **Reviews**. Click **Approve** — the confirmation dialog itself does the
honest thing: it tells you there are still open findings and unresolved requirements
before you approve anyway, rather than approving silently. Cancel, and instead click
**Request changes**, type a note, submit — a new **Deferred** decision appears
immediately, and the document stays *In Review*.

## 7. Inspect the audit trail (30s)

Switch to **Timeline**: every event from *Document Created* on May 4 through *Approval
Requested* on Aug 19, each with an actor, a timestamp, and an explanation — plus the
two actions just taken, appended live. This is the reconstructable history the trust
model depends on.

## Close (20s)

> "Every score on every screen you just saw is computed from the underlying claims,
> evidence, and rules — nothing is a hand-set flag. And it's the same six documents the
> whole time: one messy contract, one rejected vendor questionnaire, one draft, two
> clean approvals, and one published policy — so the workspace feels real, not staged."

Optional detour if there's time: open **Vendor Security Questionnaire — Meridian
Analytics** (Critical risk) and show the claim *"Meridian has had zero security
incidents in the past 24 months"* — contradicted by a public breach filing the reviewer
found independently. It's the sharpest single example of *why this product exists*.
