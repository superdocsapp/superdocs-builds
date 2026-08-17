# n=3 pilot — 2026-08-13

Dev-sample run of the full pipeline: corpus → agent edit → checker score →
scripted correction → agent applies correction → re-score. Both arms, same 3
documents, same fixed order, same correction protocol. **This is a mechanism
check at n=3, not a result.** No conclusions should be drawn from these
numbers; the sample is far too small, and the memory-off arm has not yet been
run twice to establish a noise floor as the full n=20 protocol requires.

## First attempt: superseded

An earlier attempt aborted mid-run (after arm `memory_off` completed, before
`memory_on` started) when the H3-cache preflight check correctly refused to
proceed: `_CachedH3Provider` parsed the raw model response without stripping
markdown fences, so a fenced Gemini response — which is what Gemini actually
returns — scored correctly downstream but was never written to the cache. That
first `memory_off` arm's numbers are not reported below; they are superseded
by the clean re-run. The bug is fixed (`checker/h3.py` / `corrections/generator.py`),
pinned by `tests/test_corrections.py::test_h3_cache_writes_through_on_a_fenced_response`,
and confirmed live: the cache held 12 entries after the clean re-run, 0 after
the aborted one.

## The clean run

12 SuperDocs operations. `clear_cross_session_memory` before the `memory_on`
arm removed 0 entries — confirmed cold start on a key never used before.

### Curve — score before the correction round (the metric)

| Document | memory_off | memory_on |
|---|---|---|
| doc_01 | 22 | 16 |
| doc_02 | 10 | 7 |
| doc_03 | 22 | 4 |

Matched by document (fixed order, both arms): memory_on scored lower on every
document, with the gap widening across the sequence (−6, −3, −18). This is
the shape a real effect would produce. It is also the shape three data points
with no noise floor can produce by chance, or by per-document baseline
variance in the agent's own unprompted editing (see below). n=20, with a
repeated memory-off arm, is what would tell these apart — not n=3.

### Correction round confirmed working, both arms

| Document / arm | before | after correction |
|---|---|---|
| doc_01 / off | 22 | 10 |
| doc_02 / off | 10 | 2 |
| doc_03 / off | 22 | 10 |
| doc_01 / on | 16 | 9 |
| doc_02 / on | 7 | 3 |
| doc_03 / on | 4 | 1 |

Every correction round reduced the violation count. The approval flow applied
real edits live, every time.

### A confound worth flagging now, not at n=20

H8 (contractions), H9 (sentence length), and H11 (dashes) scored **zero before
any correction, in every document, both arms** — despite the corpus's fixed
24-violation profile including all three (3, 1, 2 respectively). The agent's
own "professional business writing style" edit already fixes these without
being told, the same baseline-default effect already flagged for H1 (Oxford
comma) in `northwind.json`'s leak-fingerprint classification. Practically:
these three rules never entered the scripted correction payload in this
sample, so they cannot show a memory effect either way — the curve's
discriminating power concentrates in the rules the agent does *not* already
get right by default (H2, H3, H4, H5, H6, H7, H10, H12, H13, H14). Worth
tracking at n=20: if this holds, roughly a fifth of the rubric contributes no
signal to the comparison, which changes how the deterministic/LLM split should
be read alongside it.

## Isolation mechanism used

`cross_session_memory_key="measurement_meridian_memory_on"` for the memory-on
arm's every call; `cross_session_memory=False` (no key) for memory-off.
`cross_session_search` never enabled. See PROGRESS.md decisions, 2026-08-13,
for the schema citations and the live isolation probe behind this choice.

Raw data: `results.json` in this directory. `h3_cache.json` is the run
artefact preflight requires to be present, parsing, and non-empty from the
second arm onward.
