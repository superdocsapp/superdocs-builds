# Corpus prose-stage prompt — version `seed_draft_v2`

Supersedes `seed_draft_v1`. Version 1 produced drafts carrying 6-11 house-style
violations each (Title Case headings, bullets ending in periods, month-first
dates, real passives), which made per-document difficulty depend on the language
model's incidental style rather than on the injected profile. Drafts generated
under v1 are kept in git history but are not part of the committed corpus.

IMMUTABLE once any committed corpus document has been generated from it.

- Model: `gemini-3.5-flash-lite`, temperature 0, top_p 1.
- One call per document; the only varying input is `{{TOPIC}}` and `{{INDEX}}`.
- Output is written verbatim to `corpus/seed_drafts/doc_NN.md`, then repaired by
  `corpus/normalize.py`, then injected by `corpus/inject.py`.

## Prompt body (sent verbatim)

Write a short internal project memo for a consulting firm. Plain, factual,
professional prose.

Topic: {{TOPIC}}

Length and structure:

- 320 to 400 words. This is a firm requirement.
- One `#` title, then two `##` sections, then a short closing paragraph.
- Four to six body paragraphs in total, each two to four sentences.
- One bulleted list of exactly three items.

House conventions, all mandatory:

- Headings in sentence case: capitalise only the first word and proper nouns.
  Write "Overview of findings", never "Overview Of Findings".
- Bullet items are short fragments starting with a capital letter and ending
  with NO punctuation at all.
- Active voice throughout. Never write "the review was completed by the team";
  write "the team completed the review".
- Every sentence is 25 words or fewer.
- Dates written day first with the month spelled out: "13 August 2026".
- Write "percent", never the % symbol.
- Currency as "USD 1,200" — ISO code, space, comma separator. No symbols.
- Spell out the numbers zero to nine; use numerals for 10 and above. Use
  numerals with any unit of time: "3 days", not "three days".
- No contractions. Write "it is", never "it's".
- Refer to the firm as "we" and the reader as "you". Never write "I" or "one".
- Expand any acronym on first use: "Annual Recurring Revenue (ARR)".
- One source reference in the form (Name, Year), for example (Harlow, 2024).
  No URLs.
- Do not use: leverage, utilize, robust, seamless, best-in-class, synergy,
  cutting-edge, revolutionize, delve, unlock, game-changing, world-class.
- Use unspaced em dashes for asides, like—this. Never spaced hyphens.

Everything in the memo is fictional. Do not reference any real company, person,
product, or dataset. Invent names.

Return only the memo in markdown. No preamble, no commentary.

## Why the prompt states the conventions

The generator is not the system under test. The editing agent never sees this
prompt and never sees the rubric — corrections are its only channel to the house
style. Telling the *generator* the conventions simply makes seed drafts start
near zero, so that the injector controls difficulty exactly. Whatever the model
still gets wrong is repaired deterministically by `corpus/normalize.py`, and any
document that cannot be repaired to zero is rejected rather than committed.
