# Security

## Threat model coverage

| Threat (from the directive's list) | Addressed? | Notes |
|---|---|---|
| Prompt injection | N/A this session | No agent/model reads untrusted text and acts on it anywhere in this codebase — nothing to inject into. Relevant again once PRISM AGENTDESK/INBOX/RESEARCH exist. |
| Malicious files | Partially | `writeDocx` refuses table-containing documents rather than corrupting them (a fidelity guard, not a security one). No zip-bomb, XML-entity-expansion, or size-limit guards on `readDocx`/`writeDocx`. **Not safe for untrusted uploads today.** |
| Malicious email | N/A | PRISM INBOX not built. |
| Path traversal | Not hardened | `readDocx`/`writeDocx` take a caller-supplied path directly; no sandboxing of the path itself. Fine for this session's CLI/test usage (trusted local paths); would need hardening before accepting user-supplied paths in a service context. |
| Unauthorized/cross-workspace access | N/A | No multi-tenant concept exists yet — everything runs in a single process with no notion of "workspace." |
| Secret exposure | N/A | No secrets are used anywhere in this codebase (no API keys, no credentials — everything is deterministic/offline). |
| Tool abuse / resource exhaustion | Not hardened | No timeout, no memory cap, no recursion limit on document size. A very large or deeply-nested document could exhaust memory; untested. |

## What IS real here

- `writeDocx`'s table refusal is a genuine guard against a specific
  failure mode (silent data loss), tested (`write-docx.test.js`).
- `applyApprovedChanges`'s refusal to run with pending decisions is a
  genuine guard against under-specified mutation, tested (`gate.test.js`).
- Every workflow state transition is checked against an explicit allow-list
  (`workflow-engine.js`), tested (`registry.test.js`).

## `@prism/ui` specifically

The server introduces new surface area, addressed at the level it's
actually tested to:

- **Path traversal**: `serveStatic` normalizes the requested path and
  rejects anything resolving outside `public/` — tested with both a raw
  `..` sequence and a URL-encoded one (`server.test.js`).
- **Output escaping**: every render function in `render.js` runs
  user/document-derived text through `escapeHtml` before interpolating it
  into markup — change text, error messages, and vault labels all pass
  through this. Not fuzz-tested against adversarial input, but the
  mechanism is real and applied uniformly, not ad hoc per call site.
- **Single shared workspace, no auth**: anyone who can reach the port can
  read/mutate the one shared workspace. Fine for local single-operator use
  (its actual intended use); not safe to expose on a network without adding
  authentication and per-session isolation, neither of which exist. See
  docs/KNOWN_LIMITATIONS.md #7.
- **Not hardened**: request size limits, rate limiting, and CSRF protection
  are not implemented — the JSON body reader (`readJsonBody`) will buffer
  an arbitrarily large request into memory. Fine for a local tool handling
  files a human explicitly selected; not fine as a public-facing service.

## Bottom line

This is safe for the use case it's actually tested for: a trusted local
operator running known files through the CLI or test suite. It is **not**
hardened for untrusted input (uploaded files, network-sourced documents,
multi-tenant use) — that hardening is unstarted work, not a subtle gap.
