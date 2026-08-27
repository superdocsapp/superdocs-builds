# Capturing the two sides

The check is only as good as its input. The **before** side must be the HTML
SuperDocs put on the wire, taken before your integration touches it. The
**after** side is whatever your integration produces from it.

Get that wrong and the report is wrong in the most misleading way available: a
clean result on a broken pipeline, because both sides came out of the same
already-stripped store.

## Where the before side comes from

| Surface | Field | Notes |
|---|---|---|
| SSE stream, `document_sync` event | `content` | The prepared HTML, emitted before the agent runs. This is the canonical before side. |
| SSE stream, `final` event | `updated_html` | The document after a turn. Use as a *before* side only for the next round trip. |
| `POST /v1/chat` response | `updated_html` | Same content, non-streaming path. |
| Multi-document session | `focused_document_id` | Says which document the HTML belongs to. Pass `--document-id` to pick one. |

## With the CLI

`chunk-guard capture` reads a saved SSE stream, a single event as JSON, an array
of events, or a response body, and writes the HTML out.

```bash
# A saved stream
chunk-guard capture stream.log --out before.html

# One event, or a response body, as JSON
chunk-guard capture event.json --out before.html

# Multi-document session: pick the document you are checking
chunk-guard capture stream.log --document-id d1 --out before.html

# The after side of the previous turn, as the before side of this one
chunk-guard capture stream.log --event final --out before.html
```

When a stream carries several `document_sync` events, the last one wins: it is
the newest prepared HTML.

## Recording a stream to a file

```bash
curl -N "https://api.superdocs.app/v1/chat/${SESSION_ID}/stream?job_id=${JOB_ID}" \
  -H "Authorization: Bearer ${SUPERDOCS_API_KEY}" \
  | tee stream.log
```

`SUPERDOCS_API_KEY` is a placeholder — never commit a real key, and never put one
in a fixture.

## From the browser, in your own app

Drop this into the client that already subscribes to the stream. It captures both
sides at the two moments that matter, and downloads them as files you can commit
as a fixture.

```js
let capturedBefore = null;

eventSource.addEventListener('document_sync', (event) => {
  const payload = JSON.parse(event.data);
  capturedBefore = payload.content;          // before your editor sees it

  editor.setHtml(payload.content);           // your normal apply step
  const capturedAfter = editor.getHtml();    // straight back out again

  save('before.html', capturedBefore);
  save('after.html', capturedAfter);
});

function save(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/html' }));
  Object.assign(document.createElement('a'), { href: url, download: name }).click();
  URL.revokeObjectURL(url);
}
```

Then:

```bash
chunk-guard check before.html after.html
```

## In code, without files

```js
import { checkRoundTrip, extractDocumentHtml } from 'superdocs-block-identity-guard';

eventSource.addEventListener('document_sync', (event) => {
  const before = extractDocumentHtml(event.data).html;
  editor.setHtml(before);
  const report = checkRoundTrip(before, editor.getHtml());
  if (!report.ok) console.warn(report.findings);
});
```

`extractDocumentHtml` accepts the same shapes the CLI does, so the one-event JSON
an `EventSource` hands you works directly.

## Turning a capture into a fixture

A committed before/after pair is what makes this a pipeline check rather than a
one-off investigation:

1. Capture a pair from a real session, covering the block types your product
   actually uses — headings, paragraphs, lists, list items, blockquotes, code
   blocks, horizontal rules, tables, and any diagram or equation nodes.
2. Strip anything you do not want in a repository. The HTML is document content,
   so use a synthetic or public document, never anyone's real paperwork.
3. Commit both files, and add the pair to your CI job ([CI.md](CI.md)).

The eleven pairs in `fixtures/` are exactly this, written by hand: each one is a
single failure, small enough to read in full.

## Two ways to capture wrongly

**Both sides from your own store.** If the before side is read back out of your
database, it has already been through whatever strips attributes, and the check
compares a stripped document to a stripped document and calls it clean. Take the
before side from the wire.

**The after side taken too early.** Serialise after the editor has fully applied
the content, not from an intermediate state — otherwise the report describes a
document that never existed.
