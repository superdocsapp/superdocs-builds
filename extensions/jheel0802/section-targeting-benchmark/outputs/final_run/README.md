# Final run evidence

- `results.csv` contains the sanitized latest adjudicated attempt for each of the 60 official cases in Benchmark run 4.
- `summary.json` contains targeting, strict, latency, operation, failure, and secondary-experiment metrics calculated from that same final run.
- `final-result-dashboard.png` captures the final 60/60 Results dashboard. The CSV and JSON are the authoritative metric artifacts.

Section targeting and strict/end-to-end accuracy are both **56/60 (93.3%)**. Search targeting is **42/43 (97.7%)** and edit targeting is **14/17 (82.4%)**. The pre-declared cap was **60 operations**; actual API-reported usage was **38 operations**, so the run was within budget. Dollar spend was not reported by the API.

Secondary experiments do not change the official first-attempt results. Applied-edit verification reviewed 15 approvals (13 landed correctly, 2 could not be determined, 0 unrelated changes). Guided recovery recovered both of its 2 attempts.
