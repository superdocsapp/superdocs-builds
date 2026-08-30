# Security

## Credentials

- The SuperDocs API key is entered once via the "Connect Account" command
  and stored only in VS Code's `SecretStorage` (`context.secrets`), which is
  OS-encrypted (Keychain / Credential Manager / libsecret depending on
  platform). It is never written to `settings.json`, never logged, and
  never sent to the webview.
- `SuperDocsApiError` messages (surfaced to the user on connection failure)
  come from SuperDocs's own `detail` field or `statusText` — neither path
  includes the key itself.

## Document integrity (write-back safety gate)

The revert/write-back path reconstructs document HTML by flattening a
chunk map (`serializeChunks`). Two things were found and fixed during
hardening, not assumed safe:

1. **Nested chunk ids were previously double-counted.** `data-chunk-id` can
   appear on nested elements (a table, and separately on its rows and
   cells). The original `parseChunks` captured nested ids as *separate* map
   entries in addition to the parent's full HTML — flattening that map back
   into a document would have duplicated the nested content. Fixed:
   `parseChunks` now only captures top-level (non-overlapping) chunks;
   nested content is part of its parent's own captured HTML, never a
   second, separately-serialized entry. Covered by
   `chunkDiff.test.ts`'s "document integrity" tests, including an explicit
   assertion that duplicated content (e.g. "A1" appearing twice) does not
   occur.
2. **Whether this model fully captures a real SuperDocs document's
   structure (wrapper elements, interstitial content) was never verified**
   — this sandbox has no live account to check against. Rather than assume
   it's complete, `canSafelyRoundTrip(html)` (`chunkDiff.ts`) checks it
   *empirically*: `serializeChunks(parseChunks(html)) === html`. Every live
   write-back (`liveSideEffects.ts`) calls this on the current document
   immediately before writing anything, and throws
   `UnsafeDocumentStructureError` (caught by `ReviewStore` and turned into a
   `conflicted` state, not a crash) if it fails, rather than risk silently
   dropping or corrupting content the model doesn't account for. This makes
   "is it safe to write back" a property checked against the real document
   in front of the code, not an assumption about SuperDocs's HTML shape in
   general.

**Verdict on independent revert:** the *decision* of what to revert and
whether it's safe to touch (is this the only change on this chunk, has
anything else moved it) is sound and tested end-to-end
(`reviewStore.test.ts`, `revertEngine.test.ts`). The *mechanism* that
writes the result back to SuperDocs is gated by the check above but still
relies on an AI-mediated endpoint rather than a confirmed deterministic
write (see next section) — so "safe" currently means "provably safe to
attempt, and refuses rather than corrupts when it can't prove that," not
"guaranteed atomic against a live account," which was never verified.

## The live write-back endpoint itself

No plain "overwrite this document's HTML verbatim, no AI involved" endpoint
was found in SuperDocs's documented API. `POST /v1/chat` accepts an
optional `document_html`, but it is still an AI-mediated edit call. This
sandbox's network egress does not reach `api.superdocs.app`, so this could
not be smoke-tested against a real account either way.
`LiveSuperDocsSideEffects.applyPatch` computes the exact target HTML
client-side (no AI involved in *deciding* the content — that part is fully
tested) and asks SuperDocs to accept it verbatim via a minimal instruction.
If a live account shows this isn't applied deterministically in practice,
this is the one method that needs to change.

## Webview

- Content-Security-Policy (set on every render, `webviewRender.ts`
  `renderDocument`): `default-src 'none'; script-src 'nonce-<random>';
  style-src 'nonce-<random>'; img-src <webview origin> https: data:`. No
  `'unsafe-inline'`, no `'unsafe-eval'`, no remote script/style origins.
  Verified by test that the rendered document never contains either unsafe
  directive.
- A fresh nonce is generated on every render — the inline `<style>`/
  `<script>` blocks are the *only* thing the CSP permits to execute.
- SuperDocs document HTML (before/after fragments) is untrusted input,
  sanitized with **`sanitize-html`** (a maintained library — swapped in
  during hardening for what was previously hand-rolled regex) via an
  explicit tag/attribute allowlist (`webviewRender.ts` `sanitizeFragment`):
  ordinary formatting tags, tables, links on `http(s)`/`mailto` only, plus
  `data-chunk-id`/`colspan`/`rowspan`/`align`. Everything else — scripts,
  iframes, forms/inputs, event handler attributes, `style` attributes,
  `javascript:`/`data:` URLs — is dropped, not disarmed-in-place. Tested
  against SVG-based script vectors, style-attribute vectors, and fake
  credential forms, in addition to the original script/iframe/event-handler
  cases. This is defense in depth, not the primary boundary — the CSP above
  is what actually prevents execution even if sanitization were somehow
  bypassed.
- All non-HTML text (claims, explanations, status labels, ids, the turn's
  instruction and reply) goes through `escapeHtml()`, never raw string
  interpolation.
- Inbound `postMessage` from the webview is validated by
  `isValidIncomingMessage()` (`reviewPanel.ts`) against an exact shape and
  an allow-list of five action strings before anything is dispatched.
  Anything else is silently dropped.
- No `localResourceRoots` are granted to the webview.

## Untrusted input more broadly

- Agent claims (free text) are treated as just that — text to display, and
  input to `looksLikeCompletedEditClaim()`'s keyword heuristic. They are
  never treated as ground truth for whether a document actually changed;
  `reconcileTurn()` always grounds "actual" in the objective chunk diff.
- SuperDocs job/session identifiers are used only as opaque keys; none are
  interpolated into a shell command or file path.

## Audit trail semantics

Audit records store `beforeContent`/`afterContent` — raw HTML snapshots —
not version identifiers. These fields were previously named
`fromVersion`/`toVersion`, which implied a version-tracking guarantee they
never provided; renamed during hardening. SuperDocs's actual version/
checkpoint concepts (`checkpoint_id`, `turn_index`) are a separate,
not-yet-wired concept — see `docs/GAP_ANALYSIS.md`.

## Logging

- `console.error` in `sessionWatcher.ts`'s error handler logs the error
  object and, when available, the session id — never document contents or
  the API key.

## Known gaps

- Retry-After is honored for the polling loop's own requests (429 pauses
  polling for the indicated duration); write-back calls
  (`liveSideEffects.ts`) do not yet have the same backoff.
- `applyPatch`'s reliance on an AI-mediated endpoint (above) is a real,
  stated limitation, not a solved problem.
