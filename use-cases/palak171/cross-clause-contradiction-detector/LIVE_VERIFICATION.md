# Live verification against the real SuperDocs API

Run on 2026-08-08 against `sample_contracts/vendor_services_agreement.txt`,
which contains one genuine contradiction (Clause 18 vs 20: 60-day vs 30-day
renewal notice) and one deliberate near-miss (Clause 7 vs 12: undisputed vs
disputed invoices — a carve-out, not a conflict). See README for why the
sample is built this way.

## Result 1 — model tier matters, a lot

`detect` with default settings (`model_tier` unset, i.e. `core`):

```
--- Contradiction report ---
No cross-clause contradictions found.
---
```

**False negative.** The default/cheapest tier missed the genuine
contradiction entirely.

`detect --model-tier max --thinking-depth deep`, same document, same prompt:

```
--- Contradiction report ---
1. Clause 18 vs Clause 20: The contract contains conflicting numeric terms
for the same non-renewal obligation, specifying that notice must be given
"at least 60 days before the end of the then-current term" while later
stating non-renewal is permitted "by giving 30 days' notice before the end
of the then-current term."
---
```

Caught correctly, **and** it did not flag the Clause 7/12 near-miss either
time — precision held at both tiers, only recall differed. Practical
takeaway for anyone building on this: `core` is fine for prose generation,
not for what this task actually measures (precision on subtle contradictions).
Any real deployment of this detector should default to `max`/`deep` for the
detection pass specifically, and eat the extra operation cost — it's exactly
one operation either way (deeper thinking doesn't change billing here, it's
still one op per `/v1/chat` call).

## Result 2 — the resolve pass, live

`resolve <session> --auto-approve --export reviewed_contract.docx` on the
session that had run detection at `max`/`deep`:

- SuperDocs proposed 2 edits (one per clause needing alignment), both with
  `chunk_id`-scoped diffs, both approved and applied.
- Exported `.docx` verified afterward with `python-docx`: Clause 18 now reads
  "Renewal (30 days)"; Clause 20 spells out "30 days written notice"
  explicitly. The contradiction is genuinely gone from the output file, not
  just claimed in a chat response.

## Bug found: our own script, not SuperDocs

`cmd_resolve`'s final `print(job["result"]["response"])` crashed with
`UnicodeEncodeError` on Windows — SuperDocs' response text contained an
emoji character, and the default Windows console codepage (cp1252) can't
encode it. Fixed in `contradiction_detector.py` by forcing UTF-8 on stdout/
stderr at startup (`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`).
Filed here per the task brief's "what broke" question — this is a bug in our
integration code, not a SuperDocs API defect, and is called out as such.
