# Deterministic fixture server

`server.mjs` is a contract-derived, sanitized local HTTP fixture. It binds a random loopback port and models pre-signed upload/download, document processing, async job states, repeated HITL/continuation rounds, named-session reuse, multiple export formats, and deterministic Stage 4 faults.

Assertions remain strict:

- API routes require the fixture bearer credential.
- Signed storage routes must not receive the SuperDocs Authorization header.
- Request bodies are captured and checked against current documented fields.
- No remote deletion/archive route is implemented; session-remove tests prove no such call occurs.
- Malformed/schema/error modes remain explicit.
- Application/infrastructure 429, transient 500/502/503, ambiguous chat drops, interrupted upload/polling, expired jobs, truncated/expired downloads, and completion-before-export expose exact call counters.
- Stress streaming mode hashes and counts upload chunks without retaining the body and streams a valid generated OOXML export in bounded chunks.

The payloads are deterministic fixtures, not recorded production traffic. `cassettes/contract-derived-stage4.json` is likewise labeled contract-derived; it is replayed without a key or network. They contain no real credential, live signed query, private document, or live identifier.
