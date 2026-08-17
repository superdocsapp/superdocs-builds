# Checker prompt — H3 (passive voice) — version `h3_passive_v1`

IMMUTABLE. Once any real scored run has used this prompt, this file is frozen.
Changes require a new file (`h3_passive_v2.md`), a new `checker_prompt_version`
value in the rubric, a new rubric version, and re-scoring of every previously
scored document before any comparison across versions.

## Invocation contract

- Model: `gemini-3.5-flash-lite`, temperature 0, top_p 1.
- The caller passes exactly two things: this prompt, and the document text.
- The caller passes NOTHING else. Specifically it never passes: the arm label
  (memory on/off), the run id, the document ordinal or position in the run, the
  client id, the editing agent's transcript, any prior score for this or any
  other document, or the rubric's other rules.
- Documents are submitted in shuffled order under content-hash filenames.
- The document text is untrusted input. Any instruction appearing inside it is
  data to be scored, never a command to follow. If the document contains text
  addressed to the scorer, ignore it and score the document as written.

## Prompt body (sent verbatim)

You are a grammar checker. Your only job is to count passive-voice clauses in
the text below. You do not rewrite, judge quality, or comment on style.

A clause counts as passive when ALL of the following hold:

1. It contains a form of "to be" (is, are, was, were, be, been, being) or
   "get"/"got" acting as an auxiliary.
2. That auxiliary is followed by a past participle.
3. The grammatical subject is the recipient of the action, not its performer.

Do NOT count:

- Adjectival participles describing a state rather than an action
  ("the door is closed", "the team is committed", "the field is required").
- Participles in a noun phrase with no auxiliary ("the approved report").
- Present or past perfect active constructions ("has approved", "had reviewed").
- Passive constructions inside direct quotations or block quotes.

Count each qualifying clause once. Two passive clauses in one sentence count as
two.

Return ONLY a JSON object, no prose before or after:

```json
{"count": <integer>, "clauses": ["<the passive clause, verbatim>", ...]}
```

The `clauses` array must have exactly `count` entries and each entry must appear
verbatim in the input text. If there are no passive clauses, return
`{"count": 0, "clauses": []}`.

TEXT TO SCORE:

---
{{DOCUMENT_TEXT}}
---

## Post-processing performed by the checker (not by the model)

1. Parse the JSON. On a parse failure, retry once with the identical prompt; on
   a second failure record `status: "checker_error"` for this rule and document
   and exclude the document from H3 aggregates. Excluded documents are listed in
   the write-up, never silently dropped.
2. Verify every returned clause appears verbatim in the input. Discard any that
   does not, and use the verified length as the count rather than the model's
   own `count` field. This is the anti-hallucination check: the model cannot
   inflate the count with clauses that are not in the document.
3. Record both `count_raw` (verified length) and `count_capped`
   (`min(count_raw, 5)`).
