# The demo vault

A complete, small manuscript that exercises every feature the compiler claims — so that a stranger can see the whole thing working in one command, and so that the README's screenshots come from real output rather than a mock-up.

```bash
npm run demo            # compiles to HTML, offline, no key
npm run demo:export     # adds PDF and DOCX (needs SUPERDOCS_API_KEY)
```

## What is in it

| | |
|---|---|
| `Manuscript.md` | The spine: book metadata plus 11 entries across front matter, three parts and back matter |
| `Front/Preface.md` | Uses a transclusion (`![[Shared/Rights Statement]]`) and a citation |
| `Chapters/01…08` | Eight chapters with figures, both footnote forms, all three citation forms, cross-references to figures and to other chapters, a callout, and a table |
| `Back/` | Acknowledgements and an author note |
| `Figures/*.png` | Seven generated placeholder plates |
| `References/library.bib` | Seven BibTeX entries — including `uncited1999`, which is deliberately never cited so the compile reports it |
| `Shared/Rights Statement.md` | A note that is transcluded but is **not** on the spine |

## Deliberate imperfections

Two things in this vault are wrong on purpose, because a demo where everything resolves proves nothing about what happens when something does not:

- **`uncited1999`** is in the bibliography and cited nowhere. The compile reports it as an `info` diagnostic and leaves it out of the printed reference list.
- The manuscript is written so that breaking one thing — deleting a figure, renaming a `.bib` key — produces a clear, located error rather than a silently wrong book. Try it: rename `barrow1971` in `References/library.bib` and recompile.

## Everything here is fictional

*The Cartographer's Dilemma*, R. M. Alderney, Fenwick & Hale, the Northern Survey, and every source in the bibliography are invented for this demonstration. No real person, publisher, survey or archive is depicted. The figures are generated colour plates, not photographs or maps.
