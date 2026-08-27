# The rule table

Every finding names a transformation. This page says what triggers each rule,
what evidence it rests on, and what to do about it.

`chunk-guard rules` prints an abbreviated version of this table.

A note on confidence, which every finding carries:

- **high** — the evidence is unambiguous: an exact text and tag match, or a
  count that admits one reading.
- **medium** — the reading is the best available: the text was matched by
  similarity rather than exactly, or two transformations produce the same trace
  and only one of them is named.
- **low** — the block had too little text to identify. Treat as a pointer, not a
  conclusion.

---

## Losses

### `LOST_ATTRIBUTE_STRIPPED` — error

The block is still in the document, with the same tag and the same text, and only
the identifier is missing.

Two shapes, distinguished in the cause line:

- the node kept **other `data-*` attributes** — the filter names the attributes it
  keeps, and `data-chunk-id` is not on the list;
- the node kept **`class`/`style` but no `data-*`** — a sanitiser or editor schema
  with an attribute allowlist: known attributes through, unknown attributes
  dropped.

**Fix**: allow the attribute through. The integration guide has the pattern for
each editor — a schema extension plus an upcast/downcast pair, a sanitiser
allowlist entry, or an attributor registration. Verify with a test that runs
every block type through your editor, not just paragraphs.

### `LOST_NODE_REBUILT` — error

The text survived under a different tag: `h2` came back as `div`, `table` came
back as `ul`. The node was reconstructed by a different document model rather
than edited in place, and the identifier was not carried across.

**Fix**: whichever component rebuilds the node has to copy unknown attributes
onto the node it creates. If the conversion is deliberate (your editor has no
table support, say) the identifier still has to ride along, or that block becomes
unaddressable.

### `LOST_MARKDOWN_HOP` — error

The block came back with no attributes at all, sitting among neighbours that are
equally bare, and tags a rich document model can express — `section`, `span`,
styled wrappers — are gone from the document.

**Fix**: find the markdown or plain-text conversion in the middle of the pipeline.
A conversion to text cannot carry attributes; the HTML has to travel as HTML.

### `LOST_BLOCK_REMOVED` — error

Nothing in the after document carries this text, or anything close to it. The
block was deleted, replaced wholesale, or never rendered by the integration.

**Fix**: this is usually not an attribute problem. Either the user deleted the
block (in which case the capture is fine and the finding is expected), or your
render step is dropping a node type it does not recognise.

### `LOST_SUBTREE` — error

Three or more blocks that share the same nearest surviving ancestor all lost
identity. One transformation is responsible for all of them, and the finding says
which one, names the ancestor the loss stops at, and lists every member with its
own rule.

**Fix**: fix the transformation named in the cause line. The whole group goes
with it.

### `IDS_REGENERATED` — error

Not one identifier survived, and the after document carries identifiers of its
own — often in the same shape, which is why this failure survives inspection.

The editor set its own content instead of applying the `document_sync` HTML. Every
subsequent change batch will target identifiers that no longer exist.

**Fix**: apply `document_sync.content` to the editor rather than loading the
document from your own store. The identifiers must be the ones SuperDocs sent.

### `ALL_IDS_STRIPPED` — error

Every identifier is gone and none was minted. The cause line distinguishes a
document-wide attribute filter (other attributes survived) from a whole-document
markdown hop (no data attributes anywhere, and no tag a markdown round trip
cannot express).

**Fix**: as for `LOST_ATTRIBUTE_STRIPPED` or `LOST_MARKDOWN_HOP`, applied to the
whole pipeline rather than one node type.

---

## Ambiguity

### `DUPLICATE_ID` — error

One identifier on two or more blocks after the round trip: a copy-paste, a split
block, or a node the editor cloned. This is the dangerous one — a change batch
targeting that identifier is ambiguous, and the edit lands on whichever node your
applier finds first, which is not stable between runs.

**Fix**: when your editor splits or clones a block, the new node needs a new
identifier, not a copy of the old one. SuperDocs assigns identifiers to blocks it
has seen; a block you created locally should carry none at all rather than a
duplicate.

### `DUPLICATE_ID_IN_SOURCE` — warning

The before document already had the same identifier twice, so nothing downstream
can resolve it. Usually a capture assembled from two sources, or a document
stitched together locally.

**Fix**: check where the before HTML came from before trusting any other finding
in the report.

---

## Attributes other than the identifier

### `DATA_ATTRIBUTE_DROPPED` — error, or warning

The block kept its identifier and lost another `data-*` attribute. The same
filter that drops identifiers drops these, and they carry content that cannot be
recovered from the rendered output.

Error when the attribute is one whose loss breaks something specific:

| Attribute | What breaks |
|---|---|
| `data-part-type` | the block stops being recognised as a header, footer, footnote or comment |
| `data-diagram-source`, `data-diagram-type`, `data-mermaid` | the diagram degrades to an empty block on the next edit cycle |
| `data-latex`, `data-equation` | the equation loses its source |
| `data-citation-id`, `data-citation` | the citation stops resolving and will not survive export |
| `data-footnote-id` | the footnote reference loses its target |

Warning for any other `data-*` attribute, because the consequence depends on what
put it there. Editor bookkeeping attributes (`data-slate-*`, `data-testid`,
`data-node-view-*`, and similar) are ignored entirely.

**Fix**: allow `data-*` through as a family rather than naming attributes one at
a time. Every one of these has the same silent failure mode as the identifier.

---

## Reported, but not failures

### `PART_OMITTED` — info (error under `--strict-parts`)

An out-of-flow part — header, footer, footnote body, comment — is not in the
after document. Omitting one is normal for an editor with no header/footer
affordance, and it never deletes anything: the server treats an absent part as
normal, and deletion requires passing its identifier in `deleted_part_chunk_ids`.

Reported so it is visible; failing on it would train teams to switch the check
off. Pass `--strict-parts` (or `strictParts: true`) when your integration is
supposed to render and return parts.

Note the distinction: a part that is *present* in the after document with its
identifier stripped is an ordinary loss, and is reported as one.

### `BLOCK_MOVED` — info

Identity intact, position changed. Reported separately so a reorder is never
mistaken for a loss.

Position is measured against the longest run of blocks still in their original
relative order, so deleting one block does not report everything after it as
moved.

### `NEW_IDS` — info

Identifiers in the after document that were not in the before document. Normal
when the user kept typing. When they outnumber the carried-over ones, the cause
line says so: an editor minting its own identifiers looks exactly like this.

### `CONTENT_CHANGED` — notice

The block kept its identifier and changed its text. Ordinary editing, off by
default; switch it on with `--include-content-changes` to audit what a round trip
rewrote.

### `NO_IDS_IN_SOURCE` — error

The before document carries no identifiers at all, so there is nothing to
validate. If another identifier attribute is present, the finding names it.

**Fix**: capture the before side from a `document_sync` event or a chat response,
before your editor touches it. See [CAPTURE.md](CAPTURE.md).
