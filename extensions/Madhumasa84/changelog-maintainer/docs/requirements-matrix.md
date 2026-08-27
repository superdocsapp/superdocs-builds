# Page-301 requirement matrix

| Literal page-301 requirement | Implementation | Evidence |
| --- | --- | --- |
| Standing living changelog | Canonical Markdown plus release manifests | `src/canonical.js`, integration tests |
| Targeted update per release | Candidate block contains only the requested release | Preview tests |
| New entries in house style | Style inference and deterministic renderer | Style unit test |
| Older entries untouched | Append-only bytes and reread hash | Ten-release test |
| Re-export on each cycle | PDF and DOCX derived after approval | Export tests |
| Published artifact and maintained document do not drift | Output hashes and dry-run plan reference canonical source | Export/publication tests |
| Releases 1–N−1 byte-identical | Exact prefix bytes and SHA-256 at every iteration | Ten-release integration test |
| Style consistent across ten releases | Ten deterministic fixture inputs | Ten-release integration test |
| Explicit stopping condition | Ten-release maximum in manifest and workflow | Stop-rule test |
| No-spend preview mode | Preview performs no network/API operation | Preview test and zero-network implementation |
| Offline provenance | 0 live/API/billable operations; no external publication | Evidence manifest and release-gate run |
| Classification boundary | Structured release JSON; no external LLM or MCP | README, design, and offline fixtures |
| One explicit decision per item | Stable item IDs, incomplete sets remain pending, repeated/conflicting IDs rejected | Partial-decision and duplicate-decision integration tests |
| Durable interrupted runs | Checkpoints after each consequential transition and same-run resume | Interruption/resume integration test |
| Atomic writes and safe overwrite | Temp-file + rename; output preflight before append; overwrite is opt-in | Atomic-write and existing-output tests |
| Exact approved-byte authorization | Candidate and approved blocks are hash-bound and rechecked on recovery | Approved-byte tamper integration test |
| Idempotent reruns | Completed approve/resume return stored result without a second append | Completed-rerun integration test |
| Security evidence | Repository scan rejects credential, signed-query, and machine-path matches | `test/security-scan.test.mjs` |
| Never retrigger on own output | Origin metadata and canonical-path checks | Self-trigger test |
| S2 / chat and export / extensions-folder PR route | Documented package boundary and local dry-run publication plan | README and publication test |

The PDF assigns no numeric score. “S2” is its default difficulty band, not a point value.
