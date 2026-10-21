# Public-safety checklist

- [x] No public API key, bearer token, cookie, signed URL, or private header.
- [x] No raw live provider payload, session ID, job ID, durable document ID, or private source document.
- [x] Live evidence is count/hash sanitized and explicitly labeled.
- [x] Synthetic manuals, HTML, JSON reports, metrics, batch manifests, and PDFs contain no customer material.
- [x] `.env`, caches, `node_modules`, test results, reports, and local diagnostics are ignored or excluded.
- [x] No absolute local paths are used as public evidence claims.
- [x] README and docs distinguish LIVE, OFFLINE VERIFIED, SYNTHETIC, and BLOCKED.
- [x] No approval decision or export was sent to the blocked live M1 job.

Before staging, inspect `git ls-files`, scan public text for credential/identifier patterns, run `git diff --check`, and manually review the artifact map.
