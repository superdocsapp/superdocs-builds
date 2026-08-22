# SuperDocs bugs found while building the Freelancer Billing Bundle

## 1. Job reports "completed" while silently skipping requested edits

**Reproduction:**

- Start a chat/async job with `approval_mode: ask_every_time`, requesting multiple field fills (client name, engagement title, two computed totals) plus a table fill.
- Approve each proposed change across several review rounds (job proposes changes in small batches, not all at once).
- After approving the final visible batch, job status transitions directly to `completed` instead of proposing the remaining fields (Client, Engagement, Total Hours, Total Amount were never filled).
- Exported document confirmed via byte-level inspection: those four fields still show their original placeholder text.

**Impact:** the job's own `status: "completed"` is not a reliable signal that requested edits were actually applied. A caller trusting job status alone would silently ship an incomplete document.

**Workaround built:** after export, we independently verify the exported docx's actual text contains every expected value before treating the job as truly complete, rather than trusting job status.

## 2. Session appears to lose context across multiple approval rounds, degrading real values into generic placeholders

**Reproduction:**

- Same multi-round approval session as above.
- After 2-3 rejected changes in a row, subsequent proposed edits for other fields (fields we hadn't touched yet) came back as `<mark>Please fill: Client Name</mark>` and `<mark>Please fill: Engagement details</mark>` instead of the actual values originally provided in the instruction.
- One further round returned an incorrect numeric value (Total Hours: 40 instead of the correct 60) with no indication of uncertainty.

**Impact:** a session's grip on the original instruction appears to degrade after repeated review rounds, producing plausible-looking but wrong or generic content instead of failing clearly.
