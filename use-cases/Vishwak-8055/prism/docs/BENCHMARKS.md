# Benchmarks

**No benchmarks were run this session.** Stated plainly rather than filled
with placeholder numbers.

## Why

The directive's benchmark requirements (PRISM SCALE: 10/50/200/500-page
documents, p50/p95/p99 latency, memory, token/cost measurement) need (a)
a real document corpus at those scales, which doesn't exist (PRISM
TRUTHSET is not built — only two short fixture contracts exist), and (b)
for the token/cost dimensions specifically, real model calls, which this
codebase deliberately makes none of (see KNOWN_LIMITATIONS #3).

## What would be honest to measure right now

The deterministic pipeline (read → align → classify → apply → write →
verify) on the existing 2-paragraph-change fixture completes in well
under a second end-to-end (visible in the `node --test` duration output,
e.g. the full composed-workflow test runs in ~80ms including two full
DOCX read/write cycles). That number is real but means almost nothing
about behavior at 50 or 500 pages — extrapolating from it would be exactly
the "claimed savings without measurement" the directive prohibits.

## What's needed before this section can have real content

1. A real multi-scale document corpus (PRISM TRUTHSET).
2. A benchmark harness with the directive's own required cost controls
   (start small, declare expected cost, set a hard cap, stop on breach,
   report actual spend) — not built.
3. For any capability that calls a model, an actual model integration to
   measure against — not built anywhere in this codebase.
