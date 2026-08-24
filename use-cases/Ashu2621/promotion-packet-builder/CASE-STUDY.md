# Measured Case Study

**By Ashutosh · 20 August 2026**

I built the Promotion Packet Builder to make evidence review and human approval observable instead of
hiding them behind generated prose. I declared the method before filling results and used synthetic data
only.

## Method

- Ten deterministic in-process agent runs, each with two source claims and the same mixed decision pattern:
  approve the first proposal and reject the second.
- One process-kill run at the human gate, then a new runtime over the same SQLite checkpoint.
- One local API run with ten excluded warm-ups, 500 measured health/readiness requests, concurrency 25 and
  a declared 750 ms p95 threshold.
- One bounded live SuperDocs MCP run: one primary file, two evidence attachments, async edit, explicit
  approval and provider export.
- Environment: Windows 11, Ryzen 5 5500U/12 logical processors, 16.456 GB RAM, Python 3.12.13, Node
  24.19.0 and Docker 29.6.1.

## Results

| Measure | Result |
|---|---:|
| Correct offline agent runs | 10/10 |
| Final-claim citation coverage | 100% |
| Mixed decisions respected | 10/10 |
| Agent latency median / p95 | 16.309 / 22.557 ms |
| Agent min / max / sample standard deviation | 14.293 / 22.557 / 2.597 ms |
| Killed-process recovery | 18.350 ms |
| Duplicate logical effects after recovery | 0 |
| API success at concurrency 25 | 500/500 HTTP 200 |
| API throughput / p95 | 157.40 requests/s / 360.90 ms |
| Live reviewed provider export | Valid 37,148-byte DOCX |

The live edit named both supplied evidence artifacts, paused in `awaiting_approval`, accepted the explicit
decision, reached `completed`, and retained the promotion evidence after the DOCX was reparsed.

## Constraints

The experiment was fixed in advance to synthetic fixtures, ten offline runs, one process-kill recovery,
one 500-request health/readiness load and one bounded live workflow. It allowed no employee data,
cross-session memory or autonomous approval. The stopping rule was the declared sample size or first
correctness failure; no failed sample was discarded.

## Cost to run

Offline runs had **$0 marginal service cost** on the listed local machine. The live development workflow
used one document upload, two attachment uploads, one async edit, polling, one approval and one export.
The account exposed no billed amount, so observed charge was **$0**; this is not a production cost estimate.

## Interpretation and limits

The agent timings measure deterministic local orchestration, not LLM quality or network latency. The API
load targets health/readiness only. Ten runs are enough to make this demo reproducible but not a production
capacity claim, and one live provider run is a correctness proof rather than a latency sample. Synthetic
evidence cannot establish extraction quality on real employee documents. Raw JSON is in `metrics/`.

## What I would change

I would run at least 30 provider samples across declared small/medium/large DOCX and PDF strata, record
operation counts and p50/p95/p99 end-to-end latency, and inject a failure after every external call. I
would then measure extraction precision/recall with the intended production model on a permitted labeled
corpus. Those results could support quality and capacity claims; this small study deliberately does not.
