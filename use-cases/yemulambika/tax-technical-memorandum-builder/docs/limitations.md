# Limitations

- Only HTML was requested, downloaded, hashed, and rendered. DOCX and PDF are not claimed.
- SuperDocs approval replay returned HTTP 400 during an earlier harness observation. Duplicate submission safety is therefore application-side fingerprint suppression, not a claim that the hosted approval endpoint is replay-idempotent.
- The supervised visible live workflow completed, but its exports contained an orphan duplicate `Analysis` heading after the rejected proposal was removed. The corrected renderer is regression-tested offline only; no second live API run was made.
- The completed manual browser session did not preserve trustworthy per-request timing, so the manual job duration is unavailable and is not reconstructed.
- Public evidence is deliberately minimal and sanitized: one offline screenshot plus a verification summary. Recordings, browser profiles, traces, raw results, and historical exports are excluded.
- The case, authorities, people, and monetary values are wholly fictional. This build is not tax advice and is not production-ready.
- The BFF stores state in memory. Authentication, durable storage, multi-tenant isolation, deployment hardening, rate-limit coordination, and production observability are out of scope.
