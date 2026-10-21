# Public metrics snapshot

Synthetic/offline measurements only. Each stage was sampled five times. No
SuperDocs AI operation was used and peak memory was not measured.

| metric | median ms | p95 ms | max ms | failures |
|---|---:|---:|---:|---:|
| long manual generation | 1.300 | 1.315 | 1.473 | 0 |
| page extraction | 1.336 | 1.412 | 1.417 | 0 |
| 400-page PDF ingest | 236.232 | 236.393 | 246.329 | 0 |
| FTS5 indexing | 0.043 | 0.053 | 0.177 | 0 |
| deterministic retrieval | 0.011 | 0.016 | 0.137 | 0 |
| gold ledger evaluation | 0.084 | 0.088 | 0.139 | 0 |
| evidence composition | 1.419 | 1.452 | 1.661 | 0 |
| verification | 3.003 | 3.173 | 3.856 | 0 |
| graph generation | 0.015 | 0.019 | 0.038 | 0 |
| two-page layout solve | 0.018 | 0.020 | 0.029 | 0 |
| three-card batch | 11.093 | 11.768 | 12.194 | 0 |
| second 60-page manual ingest | 36.394 | 38.241 | 45.125 | 0 |

The full raw sample remains a local generated artifact under
`artifacts/metrics/raw.json`; it is intentionally ignored by the current
checkout rules.
