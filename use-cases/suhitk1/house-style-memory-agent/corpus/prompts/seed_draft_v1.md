# Corpus prose-stage prompt — version `seed_draft_v1`

IMMUTABLE once any committed corpus document has been generated from it.
Changes require `seed_draft_v2.md` and a regenerated, re-frozen corpus.

- Model: `gemini-3.5-flash-lite`, temperature 0, top_p 1.
- One call per document. The only varying input is `{{TOPIC}}` and `{{INDEX}}`,
  drawn from the fixed topic list in `corpus/topics.json`.
- Output is written verbatim to `corpus/seed_drafts/doc_NN.md` and committed
  before the injector runs. The seed drafts are frozen artefacts: the injector
  never regenerates them, and both measurement arms read the same injected
  files.

## Prompt body (sent verbatim)

Write a short internal project memo for a consulting firm. Plain, factual,
professional prose.

Topic: {{TOPIC}}

Requirements:

- 300 to 400 words.
- One `#` title, then two `##` sections.
- One bulleted list of exactly three items.
- Include exactly one date, one percentage, one currency amount, and one
  reference to a named source.
- Do not use any of these words: leverage, utilize, robust, seamless,
  best-in-class, synergy, cutting-edge, revolutionize, delve, unlock,
  game-changing, world-class.
- Everything in the memo is fictional. Do not reference any real company,
  person, product, or dataset. Invent names.

Return only the memo in markdown. No preamble, no commentary.

## Why the constraints

The word ban and the structural requirements exist so the seed drafts start
close to compliant. The measurement needs the *injector* to be the source of
violations, at a known count, not the language model's incidental style. A seed
draft that arrives carrying its own violations makes the per-document difficulty
profile uneven, which is the exact confound the fixed profile exists to remove —
so `corpus/inject.py` refuses to run on any draft already over profile.
