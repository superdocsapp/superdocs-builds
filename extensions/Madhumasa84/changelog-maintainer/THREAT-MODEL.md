# Threat model

| Threat | Control | Test evidence |
| --- | --- | --- |
| Historical content silently rewritten | Exact pre/post byte comparison and SHA-256 prefix checks | Ten-release integration test |
| Stale approval authorizes changed text | Candidate-block hash is persisted and rechecked | Candidate tamper unit test |
| Duplicate release | Canonical marker scan and manifest checks | Duplicate-input tests |
| Self-trigger loop | Generated-origin metadata and canonical-path rejection | Self-trigger tests |
| Concurrent same-file mutation | Exclusive lock, bounded wait, stale-owner recovery, reread-before-append | Concurrency tests |
| Interrupted atomic write | Temporary files and rename; temporary cleanup | Atomic-write failure tests |
| Malicious release input | Schema allowlist, unsafe-token rejection, no evaluation of Markdown | Malicious-input tests and scans |
| Credential or signed URL leakage | No credential support, no network client, output scans | Security scan |
| Accidental publication | Publication adapter is dry-run only and reports zero network calls | Publication-plan test |
| Endless autonomous loop | Ten-release stop rule and explicit preview/approval | Stopping-rule test |

The generated PDF/DOCX metadata identifies the origin as a derived artifact. It is not accepted as structured release input. The project does not claim live SuperDocs verification, publication, or exactly-once remote delivery.
