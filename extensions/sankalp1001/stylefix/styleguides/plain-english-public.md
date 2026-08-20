# Plain English Style — Public Sector

A deliberately different guide, used to demonstrate that the linter's behaviour lives
in the attachment rather than in its code. Several rules here **contradict**
`house-product-style.md` on purpose: the same document linted against the two guides
must produce different findings, and in places opposite ones.

## Plain language

- **`short-sentences`** — Keep sentences under 25 words. Split anything longer.
- **`no-latin`** — Do not use Latin abbreviations. Write *for example* not *e.g.*,
  *that is* not *i.e.*, *and so on* not *etc.*
- **`no-jargon`** — Avoid unexplained jargon: *leverage*, *utilise*, *facilitate*,
  *going forward*, *best practice*, *stakeholder* where a named group is meant.
- **`define-first-use`** — Expand an acronym on first use.

## Obligation

- **`must-not-shall`** — Write *must* for an obligation, never *shall*. Write
  *must not* for a prohibition, never *shall not* or *may not*.
- **`no-should-for-rules`** — Do not write *should* where the rule is mandatory.

## Address and tone

- **`no-contractions`** — Write the expanded form: *do not*, not *don't*. **This is
  the opposite of `contractions-ok` in the house guide, and that is the point.**
- **`click-is-fine`** — Interface instructions say *click*, matching the guidance
  most public-sector readers already have. **Directly contradicts `ui-verbs`.**
- **`title-case-headings`** — Headings are Title Case. **Directly contradicts
  `sentence-case-headings`.**

## Numbers and dates

- **`numerals-above-nine`** — Spell out one to nine; use numerals from 10 up.
- **`long-dates`** — Write dates as 19 August 2026. Never 19/08/26.

## Rules that may change a heading

`heading_rules: title-case-headings`

Headings are protected by default. Only the rules named on the line above are allowed
to rewrite one; every other rule is refused if its fix lands in a heading. This line
lives in the guide, not in the code, so a guide that governs headings differently
changes the behaviour without a code edit.

## What the linter must never touch

Identical to the house guide, and enforced in code rather than requested of a model:
code samples, table cells, already-compliant headings, and quoted material.

## Rule triggers

- `no-latin: e.g., i.e., etc., viz.`
- `must-not-shall: shall, shall not, may not`
- `no-jargon: leverage, leverages, utilise, facilitate, going forward, best practice`
- `no-contractions: don't, doesn't, won't, can't, it's, you'll`
- `no-should-for-rules: should`
