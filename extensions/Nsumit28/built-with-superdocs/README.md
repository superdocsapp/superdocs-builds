# Built with SuperDocs

[![built with SuperDocs](https://nsumit28.github.io/built-with-superdocs/badge.svg)](https://nsumit28.github.io/built-with-superdocs/)

A "built with SuperDocs" badge you can put in your README, a gallery of projects
that use SuperDocs, and the rules for getting listed in it.

**Gallery:** https://nsumit28.github.io/built-with-superdocs/

![The gallery](docs/gallery-screenshot.png)

## Add the badge

Paste this into your README:

```markdown
[![built with SuperDocs](https://nsumit28.github.io/built-with-superdocs/badge.svg)](https://nsumit28.github.io/built-with-superdocs/)
```

HTML and reStructuredText versions are in [SNIPPETS.md](SNIPPETS.md).

Add it if your project actually uses SuperDocs. The badge links to the gallery,
so anyone who clicks it can see the list and check.

## Get listed

Two ways:

- Open an issue using the **Submit a build** template, or
- Send a pull request adding your entry to [`gallery/manifest.json`](gallery/manifest.json)

Either way, a person reviews it against three things:

1. There is a document, page or repository they can open.
2. SuperDocs did something a plain text editor could not have done as safely.
3. You can point at something that shows it — a commit, a diff, an export, a
   write-up.

Most rejections are on the second one. "I opened my file in SuperDocs" is not
enough; "I revised one clause of a contract without touching the eleven around
it, and here's the diff" is.

The full rules, including the eight reasons an entry gets turned down, are in
[CURATION.md](CURATION.md). The submission mechanics are in
[SUBMITTING.md](SUBMITTING.md). Rejections are posted with a reason, so you can
fix it and resubmit.

## What's in here

| File | What it is |
|---|---|
| `badge.svg` | The badge |
| `index.html` | The gallery page, generated from the manifest |
| `gallery/manifest.json` | The list of entries. Nothing appears on the page unless it's here first |
| `SNIPPETS.md` | Copy-paste versions of the badge for different formats |
| `CURATION.md` | What gets listed, what doesn't, and why |
| `SUBMITTING.md` | How to submit, and what happens next |
| `make_badge.py` | Rebuilds `badge.svg` |
| `make_gallery.py` | Rebuilds `index.html` from the manifest |
| `verify_*.py`, `lint_manifest.py`, `test_*.py` | Checks that run on every pull request |

## Running it locally

Rebuilding the page and running the checks needs Python 3 and nothing else:

```bash
python3 make_gallery.py     # rebuild index.html from the manifest
python3 lint_manifest.py    # every entry has evidence, a date and a decision
python3 verify_gallery.py   # the page loads nothing from the network
python3 verify_badge.py     # the badge still works through GitHub's image proxy
python3 test_lint.py        # tests for lint_manifest.py
python3 test_verify.py      # tests for verify_badge.py
```

Rebuilding the badge itself needs three packages, because the text is converted
to vector outlines:

```bash
pip install fonttools brotli uharfbuzz
python3 make_badge.py
```

The script that calls the SuperDocs API needs a key:

```bash
export SUPERDOCS_API_KEY=your-key-here
pip install markdown

python3 b3_superdocs.py --check    # re-run the before/after comparison, no API call
python3 b3_superdocs.py --edit     # sends one edit, spends one operation
```

To check whether a key works, call `GET /v1/sessions`. `GET /v1/users/me`
returns 401 even for a valid key, which makes a working key look broken.

## About the badge

- 133 × 20 px, about 7 KB, and it makes no external requests.
- The text is vector outlines rather than live text. GitHub serves README images
  through a proxy that blocks `@font-face`, and Space Grotesk (the typeface
  SuperDocs uses) isn't installed on people's machines, so a normal text SVG
  would fall back to Arial on most of them.
- Colours are taken from superdocs.app's stylesheet: coral `#f97766`, near-black
  `#110b0b`, cream `#fbfaf6`. Contrast is 18.7:1 for the left half and 7.3:1 for
  the right. White on coral only reaches 2.67:1, which fails WCAG AA, so it
  isn't used.
- There's a thin light border so the dark half stays visible on GitHub's dark
  theme, where the page background is nearly the same colour.

`camo_sim.py` serves the badge locally with the same headers GitHub's proxy
sends, so you can test changes to it before pushing.

## SuperDocs features this project uses

- **Chat editing** (`POST /v1/chat`) — used on `CURATION.md`, this project's own
  rules document.
- **Export** (`POST /v1/documents/export`) — returns a file rather than JSON.

The before and after documents are in `out/`. Section editing worked as
described: the section I asked about changed and the other nine came back
identical, including a table.

I didn't keep either sentence the AI wrote. The first answered a different
question than the section was asking, and the second made a claim about
SuperDocs that I hadn't tested. The paragraph in `CURATION.md` is mine.

## Why there's only one entry

The gallery is new. Entries come from the people who built the projects, so it
fills up as people submit. The one entry there now is my own project, which is
noted on the entry itself.

This repository isn't listed either. It's the gallery, and the gallery doesn't
list itself.

## A note on the CI workflow

`.github/workflows/curation.yml` runs the checks above on every pull request. It
works here because it sits at the root of the repository. If you copy this
project into a folder inside another repository, GitHub won't run it — workflows
only run from the repository root.

---

MIT licensed. Built by **Sumit Negi** for the SuperDocs growth task
([@superdocsapp](https://twitter.com/superdocsapp)). Not an official SuperDocs
project.
