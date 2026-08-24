# Final runtime fixes

This build addresses the Windows/browser issues observed during verification:
- PDF ASCII85 decoder now returns a concrete ArrayBuffer-backed Uint8Array, fixing the modern TypeScript generic mismatch.
- Manuscript intake controls use explicit DOM event listeners rather than relying on inline click handlers.
- The Analyze button is explicitly bound and disabled/re-enabled around requests.
- File selection immediately reports the selected filename and size.
- Demo buttons are explicitly bound.
- HTML responses are sent with no-cache headers so an old browser copy cannot silently mask UI fixes.
- The Analyze handler now targets its explicit button id.
- The deterministic heuristic retains named multi-word expressions while filtering sentence-initial ordinary vocabulary.
- SuperDocs remains server-side and credentialed; do not put API keys in browser code.
