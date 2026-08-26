# AI Editing Lab torture-test report

Generated: 2026-08-24T12:43:30.704Z

## Scope

- 100 fresh DIY document-edit requests using prompts 1–100.
- Doc A used for prompts 1–56; Doc B used for prompts 57–91.
- Prompts 92–100 used a combined A+B HTML input because the current API accepts one document payload per request; these are compatibility tests, not native multi-document UI tests.
- SuperDocs was tested separately with representative document, table, and review-flow requests.
- No proposal was automatically accepted, so source documents were not mutated by this run.

## Import results

| Document | Bytes | Imported HTML chars | Plain-text chars | Headings | Tables | Images | Import warnings |
|---|---:|---:|---:|---:|---:|---:|---|
| rough_vol_deep_hedging_torture_test_1787573519795.docx | 16744 | 7555 | 4963 | 10 | 2 | 0 | An unrecognised element was ignored: {http://schemas.openxmlformats.org/officeDocument/2006/math}oMath / An unrecognised element was ignored: w:ptab / Unrecognised paragraph style: 'Block Quote' (Style ID: quote) / Unrecognised paragraph style: 'Code Block' (Style ID: codeblk) |
| torture_test_v2_maximum_1787573501823.docx | 103872 | 9664 | 6786 | 13 | 2 | 0 | Run style with ID CommentReference was referenced but not defined in the document / An unrecognised element was ignored: {http://schemas.openxmlformats.org/officeDocument/2006/math}oMath / An unrecognised element was ignored: w:ptab / Unrecognised paragraph style: 'Block Quote' (Style ID: quote) / Unrecognised paragraph style: 'Code Block' (Style ID: codeblk) / Unrecognised run style: 'null' (Style ID: CommentReference) |

## Automated summary

| Run | Total | API completed | Failed | Unsafe markup | Structural output | P50 latency | P95 latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| DIY prompts 1–100 | 100 | 100 | 0 | 0 | 100 | 30762 ms | 49280 ms |
| SuperDocs representative | 3 | 3 | 0 | 0 | 3 | 20534 ms | 25584 ms |

### Interpretation

- **API completed** means the engine returned a schema-valid successful proposal.
- **Structural output** means a non-empty proposal was returned and passed the harness safety check.
- **Did it** and **Only that** are intentionally marked `unverified` for successful AI proposals; semantic correctness and unintended edits require human review against the prompt.
- **Survived export** is `not_available` because the current app exposes text download and import, but does not expose native DOCX/PDF export for this harness to exercise.

## Category summary

| Category | Cases | Completed | Failed |
|---|---:|---:|---:|
| baseline-round-trip | 5 | 5 | 0 |
| math-preservation | 10 | 10 | 0 |
| tables | 10 | 10 | 0 |
| lists-numbering | 8 | 8 | 0 |
| style-inline | 8 | 8 | 0 |
| structure-headings-toc | 10 | 10 | 0 |
| footnotes | 5 | 5 | 0 |
| tracked-changes | 8 | 8 | 0 |
| comments | 6 | 6 | 0 |
| multilingual | 6 | 6 | 0 |
| image-figure | 5 | 5 | 0 |
| hyperlinks-inline | 4 | 4 | 0 |
| cross-domain | 6 | 6 | 0 |
| cross-document | 9 | 9 | 0 |

## SuperDocs review flow

The JSON and CSV artifacts include the review IDs and terminal states returned by representative SuperDocs calls. Review decisions were kept explicit; no hosted proposal was silently applied to either source document.

## Detailed results

| # | Doc | Category | API | Did it | Only that | Export | Latency | Output chars | Integrity | Error |
|---:|---|---|---|---|---|---:|---:|---:|---|---|
| 1 | A | baseline-round-trip | yes | unverified | unverified | not_available | 22036 | 7555 | yes |  |
| 2 | A | baseline-round-trip | yes | unverified | unverified | not_available | 30063 | 7555 | yes |  |
| 3 | A | baseline-round-trip | yes | unverified | unverified | not_available | 28381 | 7542 | yes |  |
| 4 | A | baseline-round-trip | yes | unverified | unverified | not_available | 28844 | 7555 | yes |  |
| 5 | A | baseline-round-trip | yes | unverified | unverified | not_available | 21620 | 7553 | yes |  |
| 6 | A | math-preservation | yes | unverified | unverified | not_available | 28910 | 7559 | yes |  |
| 7 | A | math-preservation | yes | unverified | unverified | not_available | 23096 | 7614 | yes |  |
| 8 | A | math-preservation | yes | unverified | unverified | not_available | 27713 | 7555 | yes |  |
| 9 | A | math-preservation | yes | unverified | unverified | not_available | 24864 | 7628 | yes |  |
| 10 | A | math-preservation | yes | unverified | unverified | not_available | 27198 | 7723 | yes |  |
| 11 | A | math-preservation | yes | unverified | unverified | not_available | 24912 | 7555 | yes |  |
| 12 | A | math-preservation | yes | unverified | unverified | not_available | 38835 | 7555 | yes |  |
| 13 | A | math-preservation | yes | unverified | unverified | not_available | 31762 | 7559 | yes |  |
| 14 | A | math-preservation | yes | unverified | unverified | not_available | 39352 | 7555 | yes |  |
| 15 | A | math-preservation | yes | unverified | unverified | not_available | 34662 | 7607 | yes |  |
| 16 | A | tables | yes | unverified | unverified | not_available | 28956 | 7744 | yes |  |
| 17 | A | tables | yes | unverified | unverified | not_available | 30409 | 7521 | yes |  |
| 18 | A | tables | yes | unverified | unverified | not_available | 34410 | 7387 | yes |  |
| 19 | A | tables | yes | unverified | unverified | not_available | 36443 | 7526 | yes |  |
| 20 | A | tables | yes | unverified | unverified | not_available | 22874 | 7555 | yes |  |
| 21 | A | tables | yes | unverified | unverified | not_available | 36524 | 7879 | yes |  |
| 22 | A | tables | yes | unverified | unverified | not_available | 30108 | 7495 | yes |  |
| 23 | A | tables | yes | unverified | unverified | not_available | 29870 | 7949 | yes |  |
| 24 | A | tables | yes | unverified | unverified | not_available | 31161 | 7401 | yes |  |
| 25 | A | tables | yes | unverified | unverified | not_available | 30778 | 7555 | yes |  |
| 26 | A | lists-numbering | yes | unverified | unverified | not_available | 30298 | 7816 | yes |  |
| 27 | A | lists-numbering | yes | unverified | unverified | not_available | 34593 | 7555 | yes |  |
| 28 | A | lists-numbering | yes | unverified | unverified | not_available | 30536 | 7555 | yes |  |
| 29 | A | lists-numbering | yes | unverified | unverified | not_available | 24223 | 7573 | yes |  |
| 30 | A | lists-numbering | yes | unverified | unverified | not_available | 25944 | 7555 | yes |  |
| 31 | A | lists-numbering | yes | unverified | unverified | not_available | 26313 | 7627 | yes |  |
| 32 | A | lists-numbering | yes | unverified | unverified | not_available | 34764 | 7555 | yes |  |
| 33 | A | lists-numbering | yes | unverified | unverified | not_available | 23373 | 7555 | yes |  |
| 34 | A | style-inline | yes | unverified | unverified | not_available | 30502 | 7606 | yes |  |
| 35 | A | style-inline | yes | unverified | unverified | not_available | 41751 | 7607 | yes |  |
| 36 | A | style-inline | yes | unverified | unverified | not_available | 34741 | 7776 | yes |  |
| 37 | A | style-inline | yes | unverified | unverified | not_available | 31067 | 7519 | yes |  |
| 38 | A | style-inline | yes | unverified | unverified | not_available | 34254 | 7573 | yes |  |
| 39 | A | style-inline | yes | unverified | unverified | not_available | 28661 | 7572 | yes |  |
| 40 | A | style-inline | yes | unverified | unverified | not_available | 23487 | 7646 | yes |  |
| 41 | A | style-inline | yes | unverified | unverified | not_available | 34270 | 7604 | yes |  |
| 42 | A | structure-headings-toc | yes | unverified | unverified | not_available | 22972 | 6788 | yes |  |
| 43 | A | structure-headings-toc | yes | unverified | unverified | not_available | 29780 | 7833 | yes |  |
| 44 | A | structure-headings-toc | yes | unverified | unverified | not_available | 30762 | 7558 | yes |  |
| 45 | A | structure-headings-toc | yes | unverified | unverified | not_available | 27017 | 7921 | yes |  |
| 46 | A | structure-headings-toc | yes | unverified | unverified | not_available | 22648 | 7489 | yes |  |
| 47 | A | structure-headings-toc | yes | unverified | unverified | not_available | 25881 | 8076 | yes |  |
| 48 | A | structure-headings-toc | yes | unverified | unverified | not_available | 26370 | 7606 | yes |  |
| 49 | A | structure-headings-toc | yes | unverified | unverified | not_available | 32963 | 7562 | yes |  |
| 50 | A | structure-headings-toc | yes | unverified | unverified | not_available | 24529 | 7555 | yes |  |
| 51 | A | structure-headings-toc | yes | unverified | unverified | not_available | 23781 | 7568 | yes |  |
| 52 | A | footnotes | yes | unverified | unverified | not_available | 22376 | 7851 | yes |  |
| 53 | A | footnotes | yes | unverified | unverified | not_available | 21965 | 7330 | yes |  |
| 54 | A | footnotes | yes | unverified | unverified | not_available | 28979 | 7431 | yes |  |
| 55 | A | footnotes | yes | unverified | unverified | not_available | 27218 | 7358 | yes |  |
| 56 | A | footnotes | yes | unverified | unverified | not_available | 22779 | 7564 | yes |  |
| 57 | B | tracked-changes | yes | unverified | unverified | not_available | 35867 | 9649 | yes |  |
| 58 | B | tracked-changes | yes | unverified | unverified | not_available | 33537 | 9664 | yes |  |
| 59 | B | tracked-changes | yes | unverified | unverified | not_available | 31861 | 9664 | yes |  |
| 60 | B | tracked-changes | yes | unverified | unverified | not_available | 34180 | 9649 | yes |  |
| 61 | B | tracked-changes | yes | unverified | unverified | not_available | 32403 | 9664 | yes |  |
| 62 | B | tracked-changes | yes | unverified | unverified | not_available | 30581 | 9793 | yes |  |
| 63 | B | tracked-changes | yes | unverified | unverified | not_available | 27471 | 9662 | yes |  |
| 64 | B | tracked-changes | yes | unverified | unverified | not_available | 49237 | 9646 | yes |  |
| 65 | B | comments | yes | unverified | unverified | not_available | 27549 | 9664 | yes |  |
| 66 | B | comments | yes | unverified | unverified | not_available | 27958 | 9712 | yes |  |
| 67 | B | comments | yes | unverified | unverified | not_available | 31174 | 9709 | yes |  |
| 68 | B | comments | yes | unverified | unverified | not_available | 29629 | 9664 | yes |  |
| 69 | B | comments | yes | unverified | unverified | not_available | 31105 | 9665 | yes |  |
| 70 | B | comments | yes | unverified | unverified | not_available | 46833 | 9693 | yes |  |
| 71 | B | multilingual | yes | unverified | unverified | not_available | 29418 | 9674 | yes |  |
| 72 | B | multilingual | yes | unverified | unverified | not_available | 30698 | 9787 | yes |  |
| 73 | B | multilingual | yes | unverified | unverified | not_available | 31736 | 9664 | yes |  |
| 74 | B | multilingual | yes | unverified | unverified | not_available | 30414 | 9664 | yes |  |
| 75 | B | multilingual | yes | unverified | unverified | not_available | 35160 | 9681 | yes |  |
| 76 | B | multilingual | yes | unverified | unverified | not_available | 43270 | 9664 | yes |  |
| 77 | B | image-figure | yes | unverified | unverified | not_available | 31696 | 9664 | yes |  |
| 78 | B | image-figure | yes | unverified | unverified | not_available | 30776 | 9664 | yes |  |
| 79 | B | image-figure | yes | unverified | unverified | not_available | 32572 | 9774 | yes |  |
| 80 | B | image-figure | yes | unverified | unverified | not_available | 29876 | 9671 | yes |  |
| 81 | B | image-figure | yes | unverified | unverified | not_available | 34289 | 9566 | yes |  |
| 82 | B | hyperlinks-inline | yes | unverified | unverified | not_available | 48028 | 9649 | yes |  |
| 83 | B | hyperlinks-inline | yes | unverified | unverified | not_available | 31276 | 9434 | yes |  |
| 84 | B | hyperlinks-inline | yes | unverified | unverified | not_available | 30820 | 9656 | yes |  |
| 85 | B | hyperlinks-inline | yes | unverified | unverified | not_available | 36321 | 9664 | yes |  |
| 86 | B | cross-domain | yes | unverified | unverified | not_available | 37676 | 10075 | yes |  |
| 87 | B | cross-domain | yes | unverified | unverified | not_available | 2883 | 631 | yes |  |
| 88 | B | cross-domain | yes | unverified | unverified | not_available | 30168 | 9807 | yes |  |
| 89 | B | cross-domain | yes | unverified | unverified | not_available | 39157 | 10004 | yes |  |
| 90 | B | cross-domain | yes | unverified | unverified | not_available | 39220 | 9664 | yes |  |
| 91 | B | cross-domain | yes | unverified | unverified | not_available | 41616 | 9664 | yes |  |
| 92 | A+B | cross-document | yes | unverified | unverified | not_available | 54976 | 17263 | yes |  |
| 93 | A+B | cross-document | yes | unverified | unverified | not_available | 55795 | 15562 | yes |  |
| 94 | A+B | cross-document | yes | unverified | unverified | not_available | 47167 | 9569 | yes |  |
| 95 | A+B | cross-document | yes | unverified | unverified | not_available | 43235 | 9674 | yes |  |
| 96 | A+B | cross-document | yes | unverified | unverified | not_available | 39271 | 9665 | yes |  |
| 97 | A+B | cross-document | yes | unverified | unverified | not_available | 49280 | 10358 | yes |  |
| 98 | A+B | cross-document | yes | unverified | unverified | not_available | 70814 | 17263 | yes |  |
| 99 | A+B | cross-document | yes | unverified | unverified | not_available | 30441 | 9753 | yes |  |
| 100 | A+B | cross-document | yes | unverified | unverified | not_available | 69861 | 18271 | yes |  |

## Files

- `torture-test-results.json` contains complete machine-readable results.
- `torture-test-results.csv` contains the requested per-prompt grid.