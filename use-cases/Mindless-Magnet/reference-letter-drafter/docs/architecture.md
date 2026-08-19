# Architecture

One page. The diagram below is the whole system; everything else on this page is what happens when a
step fails.

## Flow

```mermaid
flowchart TB
    subgraph browser["Browser"]
        FORM["Intake form<br/>band, evidence, reservations"]
        REVIEW["Review<br/>word-level text diffs"]
        FINDINGS["Calibration findings"]
        EXPORT["Export"]
    end

    subgraph server["Next.js route handlers"]
        SESSION["/api/session"]
        DRAFT["/api/draft<br/>validate + idempotency key"]
        JOBS["/api/jobs/[id]<br/>double-parse happens here"]
        AUDIT["/api/audit"]
        APPROVE["/api/approve"]
        EXPORTAPI["/api/export"]
        USAGE["/api/usage"]
    end

    subgraph calib["Calibration (lib/calibration)"]
        LEX["Lexicon audit<br/>deterministic, free, ~1ms"]
        INJ["Injection scan<br/>deterministic, free"]
        VER["Blind verifier<br/>second model, no band given"]
    end

    subgraph sd["SuperDocs"]
        SDUP["documents/upload"]
        SDCHAT["chat/async<br/>ask_every_time"]
        SDJOB["jobs/{id}"]
        SDAPP["chat/{s}/approve"]
        SDEXP["documents/export"]
    end

    FORM --> DRAFT
    FORM --> SESSION
    SESSION --> SDUP
    DRAFT --> SDCHAT
    JOBS --> SDJOB
    REVIEW <--> JOBS
    REVIEW --> AUDIT
    AUDIT --> LEX
    AUDIT --> INJ
    AUDIT --> VER
    AUDIT --> FINDINGS
    REVIEW --> APPROVE
    APPROVE --> SDAPP
    EXPORT --> EXPORTAPI
    EXPORTAPI --> SDEXP
    USAGE -.-> FORM
```

The gate sits between `REVIEW` and `APPROVE`. Nothing reaches the document until a human decides each
change individually. The calibration findings arrive at the same screen as the diffs, which is the
point: they are only useful while the gate is still closed.

## Where state lives

| State | Where | Survives refresh | Survives restart |
| --- | --- | --- | --- |
| The letter | SuperDocs | yes | yes |
| Session + job id | `sessionStorage` | yes | no (tab close) |
| Intake | `sessionStorage` | yes | no (tab close) |
| Idempotency keys | Node process memory | n/a | no |
| Findings | React state, recomputed | no | no |

This app stores no letters and no personal data server-side. The intake is deliberately scoped to the
browser tab, because it contains a third party's performance history.

## Failure paths

| What fails | What the system does |
| --- | --- |
| SuperDocs 5xx or timeout on a read | Retry with full-jitter backoff, up to the budget, then an error naming the cause and the fix. Session id stays valid; reload resumes. |
| SuperDocs 4xx | No retry. Retrying a malformed or unauthorised request spends the budget on the same wrong request. |
| SuperDocs 429 | No silent retry loop. The error names the operation budget and points at the eval harness's `--max-ops` rule. |
| Draft request may have been accepted but the response was lost | Not retried, by design. The idempotency key means a client retry replays the original result rather than starting a second billable job. |
| Verifier model unreachable or misconfigured | Audit degrades to deterministic checks. Report says `verifier: unavailable` or `failed` with the reason. Never reported as a pass. |
| Verifier returns non-JSON | Answer discarded rather than guessed at. Status `failed`. |
| Proposed changes arrive in an unknown shape | Zero changes shown plus a stated problem. Never a partially-populated approve card. |
| Change missing id or content | That change is refused; the others still render. |
| Job asks whether to continue a large edit | Surfaced as a choice with the cost stated. Not a dead end. |
| Page refreshed mid-draft | Session and job id persist. The review resumes against the still-running job. |
| Browser tab closed | The job keeps running on SuperDocs. The ids are gone, so that letter is unreachable from this machine. Honest limitation, not handled. |
| Export warnings header malformed | Noted, document still delivered. A decode bug must not lose the file the user is waiting for. |

## Cost model

| Action | SuperDocs operations | Verifier calls |
| --- | --- | --- |
| Start a session | 0 (upload) | 0 |
| Draft a letter | ~1 | 0 |
| Run the calibration audit | 0 | 1 |
| Approve or reject changes | 0 | 0 |
| Export `.docx` | 0 | 0 |
| Continue a large edit | ~1 | 0 |

The deterministic half of the audit costs nothing and runs on every draft. The verifier is the only
recurring non-SuperDocs cost, and it runs once per distinct proposal rather than once per poll.
