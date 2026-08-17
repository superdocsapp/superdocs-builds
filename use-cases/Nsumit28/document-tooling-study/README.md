# Document tooling study

A measurement of what people are actually stuck on when software has to touch a
Word document, and a technical note written from the result.

![The published study](docs/study-screenshot.png)

**Read the study:** https://nsumit28.github.io/docx-notes/what-people-are-stuck-on/
**Read the note it produced:** https://nsumit28.github.io/docx-notes/tracked-changes-lost-in-conversion/

## What it does

`10_collect.py` queries Stack Overflow, GitHub and Hacker News through their
public APIs for fifteen document-tooling problems and records each platform's own
engagement counters — votes, views, reactions, comments, points. That produced
129 candidate pages.

`11_study.py` then selects fifteen of them against a written rule (relevance
first, then reach inside each platform, then spread across platforms and
problems) and measures each one through the API that owns it, so nothing depends
on scraping a page.

The headline result: the eight Stack Overflow questions in the set are **all
answered**, they're about converting formats and pulling tables out of PDFs, and
they've been read 652,284 times between them. The four GitHub items are **all
open**, all from 2026, and all about editing inside a document — tracked changes,
comments, tables surviving a format change, AI editing inside Word.

Getting a document out of Word is a solved problem people still look up. Changing
a document while it's still a document is being worked out right now.

`13_publish.py` renders the study and the note into a static site with no
external requests.

## How to run it

```bash
pip install markdown

python3 10_collect.py     # query the APIs, write raw/10-candidates.tsv
python3 11_study.py       # select and measure fifteen, write out/11-pages.csv
python3 13_publish.py ~/path/to/site    # render the two pages
```

`10_collect.py` uses the `gh` CLI for GitHub search, so you'll need it
authenticated (`gh auth login`). Stack Overflow and Hacker News need no key.

To re-run the SuperDocs edit on the article:

```bash
export SUPERDOCS_API_KEY=your-key-here
```

Check a key works with `GET /v1/sessions`. `GET /v1/users/me` returns 401 even
for a valid key, which makes a good key look broken.

## What SuperDocs features it uses

- **Editing inside the document** (`POST /v1/chat`) — used on the article. I
  asked for one caveat sentence to be added to a named section. The sentence it
  wrote was correct and I kept it, but it was placed before the code block
  instead of after it, so I moved it. `out/13-article-before.html` and
  `out/13-article-after.html` are the two versions.
- **Export** (`POST /v1/documents/export`).

One thing worth flagging for anyone doing the same: the edit also un-escaped
`&quot;` to `"` inside three code blocks it had been told not to change. It
renders identically so nothing broke here, but if you're editing a document whose
code samples matter, diff them afterwards.

## What's in the folder

| Path | What it is |
|---|---|
| `STUDY.md` | The study |
| `ARTICLE.md` | The technical note written from it |
| `10_collect.py` | Queries the three platforms, writes the candidate pool |
| `11_study.py` | The selection rule, the fifteen picks, and the measurements |
| `13_publish.py` | Renders both pages to a static site |
| `raw/10-candidates.tsv` | All 129 candidates, with engagement numbers |
| `out/11-pages.csv` | The fifteen selected pages and everything measured about them |
| `out/13-article-*.html` | The article before and after the SuperDocs edit |

## Limits

It's one snapshot, taken on 16 August 2026. The engagement numbers aren't
comparable across platforms and are kept in separate columns rather than added
into a score. The word counts are the question or issue body, not the whole
page. The relevance filter was my judgement — the rule is written in
`11_study.py` and the full 129-page pool is here, so you can see what was
dropped.

---

Built by **Sumit Negi** as a Round 2 candidate submission for SuperDocs.
