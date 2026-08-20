# CJK Typography and Layout Adapter

Adapts a Western-typeset HTML or Markdown document into CJK typography conventions
(and back), with a side-by-side comparison and a checklist report of every convention
applied.

For localization specialists (ja / zh-CN / zh-TW / ko) handling formal business
documents. The output is meant to read as a natively typeset business document rather
than a translated Western one, and the DOCX export preserves the typography choices.

## Conventions implemented (per locale profile)

| Convention | What happens |
| --- | --- |
| Typeface families | Serif body (Yu Mincho / SimSun / PMingLiU / Batang), sans heading, Latin fallback (Times New Roman) |
| Font sizes | Body size per market (10.5 pt ja, 12 pt zh, 10 pt ko) and a heading size ladder |
| Line spacing | 1.5 (ja/zh), 1.6 (ko); justified body text |
| Punctuation substitution | ASCII `,`/`.`/`!`/`?`/`:`/`;`/`(`/`)` to full-width forms; **ja uses `、`/`。`, zh uses `，`/`。`, ko keeps ASCII punctuation** (native convention) |
| Quote substitution | `"..."` -> `「」` (ja), `""` (zh/ko), `「」`/`""` -> `"` when reversing |
| Kinsoku (line-breaking) | No orphaned closing punctuation at line start, no opening punctuation at line end: space-stripping inside brackets plus CSS `line-break: strict` (and `w:kinsoku` in DOCX) |
| Spacing around embedded Latin/digits | Thin space (U+2009) at CJK<->Latin boundaries; existing spaces at boundaries become thin spaces; digits/`$`/units stay attached |
| Page geometry | Per-market A4 profiles: 25/20 mm ja, GB/T-style 37/28/26/35 mm zh-CN, 25 mm ko/en |
| Reverse direction | Full-width -> ASCII punctuation, thin spaces removed, full-width digits/letters half-widthized, Calibri 11 pt, Western margins |

Context-aware punctuation rules: a comma or period between Latin digits/letters is
kept ASCII (`March 15, 2026`, `1,000`, `8.25%`); sentence-final periods become the
CJK full stop; brackets are structural and always substituted.

## Usage

```bash
pip install -r requirements.txt

python cli.py <input.html|input.md> --locale ja|zh-CN|zh-TW|ko [options]
```

Options:

- `--locale ja` target CJK locale (default `ja`)
- `--reverse` adapt CJK typography back to Western (Latin) conventions
- `--out-dir out` output directory (default `out`)
- `--format html|docx|both` which adapted outputs to write (default `both`)

### Example

```bash
python cli.py data/sample/sample.html --locale ja
python cli.py out/ja/adapted.html --locale ja --reverse   # round-trip
```

## Outputs

| File | Description |
| --- | --- |
| `adapted.html` | Adapted document: rewritten text, `lang` attribute, injected page/typography CSS |
| `adapted.docx` | DOCX export: page size/margins, Normal/Heading styles with east-Asia fonts, kinsoku compatibility setting, justified line spacing, tables and lists |
| `comparison.html` | Side-by-side original vs adapted with character-level red/green diff |
| `checklist.json` | Machine-readable report: styles, page geometry, per-rule counts with before/after samples |
| `checklist.md` | Human-readable version of the same report |

The checklist counts are recorded during adaptation itself (not recomputed from the
output), and tests independently verify the counts match what actually changed in the
text.

## Design

```
data/sample/            demo documents (HTML and Markdown versions)
profiles/<locale>.json  per-market profiles: fonts, sizes, spacing, punctuation
                        maps, quote pairs, thin space, kinsoku sets, page geometry
adapter/
  text.py               rule engine: punctuation, quotes, thin spacing, kinsoku
                        attachment, half-width conversion (all stats-tracked)
  htmltree.py           HTML tree (stdlib html.parser), CSS builder, doctype/lang/style
  markdown.py           small Markdown -> HTML converter (headings, lists, tables,
                        blockquotes, code fences, inline styles)
  docx_io.py            DOCX export: geometry, styles, east-Asia fonts, kinsoku,
                        tables, lists, borders
  compare.py            side-by-side comparison HTML (difflib, char-level)
  checklist.py          checklist report (JSON + Markdown)
  pipeline.py / cli.py  orchestration and command line
tests/                  58 tests: rule engine per locale, HTML/MD handling, DOCX
                        round-trip verification, pipeline E2E with hand-computed
                        expected change counts
```

Only runtime dependency is `python-docx`; everything else uses the standard library.

## Limitations

- The adapter is a typography engine, not a translator: it converts punctuation,
  spacing, type and layout. Text that must also be translated should be localized
  first (e.g. via SuperDocs), then passed through this adapter.
- Quote alternation (`"` open/close) resets per text node; an odd number of quotes
  in a node leaves the last one opening.
- The docx export uses the primary font name from each profile stack; Word ignores
  fonts not installed on the reader's machine, so stacks are ordered by preference.

## Test

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Built for the SuperDocs engineering task (round 2) by Akshat Rai.
