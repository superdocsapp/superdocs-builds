# Product Manual and Quick-Start Builder

A product manual and its quick-start card, generated from one structured spec.

Neither document is authored. The torque figure, the laser wavelength and the
wording of every safety notice live in `spec/halyard_m1.yaml`, and both documents
are projections of it — so there is no second copy of anything to go stale. The
diagrams are rendered from the parts graph, not drawn, so an edit regenerates
them instead of asking a model to redraw something that looks nearly the same.

Built for SuperDocs Round 2. Everything about the Halyard M1 is fabricated;
there is no such machine.

## The problem it is aimed at

Every product ships a long manual and a short card, and they disagree within two
revisions. Someone corrects a torque figure in the manual, the card keeps the old
one, and the card is the one taped to the workbench. Nobody notices until a
customer follows it.

The usual fix is a process — a checklist, a reviewer, a diff. This is a
structural fix: the card cannot contradict the manual because neither of them
contains the figure.

## Try it

```bash
pip install -e ".[dev]"
```

Two commands need no API key and no network:

```bash
python -m manualbuilder.cli check
```

```
spec        Halyard M1 rev C — 12 parts, 7 steps, 7 warnings
card        6 of 7 steps, every instruction identical to the manual
locale de    structure identical, text 112% of source length
ok
```

```bash
python -m manualbuilder.cli build
```

Writes eight SVG diagrams and four documents — English and German, manual and
card — into `out/`. Open `out/manual.html` in a browser.

Then, with a key in `.env`:

```bash
python -m manualbuilder.cli publish
```

```bash
python -m manualbuilder.cli edit "raise the rail torque to 1.6 N·m" --manual doc_… --card doc_…
```

`edit` prints the proposed changes grouped by document and applies nothing.
Add `--yes` to approve them.

## How each of the three criteria is answered

### The quick-start stays consistent when the manual changes

Both documents open in **one multi-document session**, and an edit is a single
turn against both `document_ids`. One instruction produces both edits, so there
is no window in which the manual has been updated and the card has not.

`assert_touched_both` refuses a batch that proposes a change to only one of
them. An edit to a fact that appears in both documents and comes back touching
one is drift caught before it ships, and the whole batch is rejected rather than
half-applied.

Underneath that, the structural guarantee: the card is a projection of the same
spec, carrying six of the seven steps and three of the seven warnings, with its
own numbering — and every instruction on it is the manual's instruction,
verbatim. `test_projections.py` asserts that rather than trusting it.

### Diagrams regenerate rather than being re-drawn

Drawings are a pure function of the parts graph. No model is in that path at
all. Change the graph and the drawing follows; change nothing and the bytes are
identical — checked across three interpreters with different `PYTHONHASHSEED`,
because in-process equality would still hold if the layout leaned on dict
ordering, and a diagram that changed between runs would look exactly like a
diagram somebody edited.

A step's illustration highlights exactly the parts that step names. There is no
second input to the highlight set, so an illustration cannot show a part its step
does not mention. Callout numbers in the parts table come from the same
traversal as the ones in the drawing, so they cannot point at different rows.

On edit the diagram is replaced, never patched: re-render, upload, swap one
`<img src>` in one chunk.

### Localised versions keep page structure

German runs about 12% longer than the English here. That is expected, and it is
also how a translated manual reflows until a step lands on a different page from
its diagram.

`outline()` reduces a document to its structural tags with every word removed,
and `assert_same_structure` refuses a locale whose outline differs from the
source. A locale file supplies strings for ids the spec already has; it cannot
add a step or rename one, because that is a locale changing structure. A partial
translation falls back to the source language rather than leaving an empty
heading — an empty heading is a structural element with nothing in it, which is
worse than English.

`test_localize.py` deletes a heading from the German manual and asserts the check
fires, because an assertion that has never failed is not evidence of anything.

## What SuperDocs features it uses

| | |
|---|---|
| Document upload | both documents, as pre-chunked HTML so chunk-level edits are provable |
| Multi-document chat session | the anti-drift mechanism — one turn, both `document_ids` |
| `approval_mode: ask_every_time` | every turn parks at `awaiting_approval`; nothing applies itself |
| Batch approve with mixed decisions | per-change, with the top-level `approved` default |
| Image upload | the rendered SVGs, returning stable URLs for `<img src>` |
| Export | free, which is why verification leans on it |

Three API behaviours are pinned in `tests/test_superdocs.py` rather than left to
be rediscovered:

- Proposed changes come back **parsed** in `metadata.pending_changes` when
  polling, and **JSON-encoded inside a string** in
  `intermediate_responses[].content` when streaming. Anyone seeing `undefined` in
  every diff field is reading SSE, not polling.
- On approve, `approved` must appear at the **top level** as well as per change.
  It is the default for entries that omit their own, and leaving it out approves
  nothing while looking exactly like a service that ignored the call.
- Deep operations run 30 s to several minutes with no visible progress. That is
  still processing.

## Layout

```
spec/halyard_m1.yaml     the single source of truth
locales/de.yaml          strings only; cannot change structure
manualbuilder/
  spec.py                load + validate; refuses a spec that would render wrong
  diagram.py             parts graph -> SVG, deterministically
  projections.py         spec -> manual, spec -> card
  localize.py            locale fill + the structural assertion
  superdocs.py           thin API client, no product decisions
  session.py             publish, one-turn multi-document edit, approve
  cli.py                 check / build / publish / edit
tests/                   40 tests, no network
```

## What it does not do

- **It does not translate.** `locales/de.yaml` carries human-supplied strings.
  What is in scope is that a translation cannot quietly change the shape of the
  document it lands in.
- **The diagrams are an assembly breakdown, not a rendering of the machine.**
  They are drawn from the parts graph, which knows what mounts to what and
  nothing about geometry. A true exploded view needs CAD, and claiming one from
  this data would be claiming knowledge the spec does not contain.
- **One product ships.** The spec format is general; only the Halyard exists.
- **`edit` handles wording, not structure.** Adding a part changes the diagrams,
  so it goes through the spec and a re-publish. A model is never asked to redraw.

## Author

Vinayak Sharma
