# Verified small-sample result

- Run date: 2026-08-23
- Source: Live SuperDocs API
- Corpus slice: One case from each required instruction type
- Approaches: Direct instruction and search-scoped
- Declared operation cap: 12
- Actual operations: 12

## Overall

| Metric | Result |
| --- | ---: |
| Intended-change coverage | 87.5% |
| Collateral-damage rate | 6.25% |
| Precision loss | 0.1875 |
| Mean end-to-end latency | 17.625 seconds |

## By instruction type

| Instruction type | Runs | Coverage | Collateral | Precision loss |
| --- | ---: | ---: | ---: | ---: |
| Single sentence | 2 | 100% | 0% | 0 |
| One section | 2 | 100% | 0% | 0 |
| Table row | 2 | 50% | 25% | 0.75 |
| Global rename | 2 | 100% | 0% | 0 |

## By approach

| Approach | Runs | Operations | Coverage | Collateral | Precision loss | Mean latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Direct instruction | 4 | 4 | 75% | 12.5% | 0.375 | 13.298 seconds |
| Search-scoped | 4 | 8 | 100% | 0% | 0 | 21.952 seconds |

## Failure evidence

The direct `table-internet-amount` run changed the requested amount from ₹1,500 to ₹1,800, but the returned table no longer carried `data-chunk-id` attributes on its rows. The target row therefore failed its structural after-state check, and the three protected rows registered as collateral changes. This is a useful precision failure: the visible values were correct, but the document's edit-addressability was damaged.

The search-scoped run of the same case achieved full coverage with zero collateral. The first read-only retrieval attempt was isolated and counted within the declared cap; when it behaved like an edit, its document session was discarded rather than scored. The implementation now always runs retrieval in a separate session and maps any retrieved IDs into a clean evaluation session.

This small sample is integration evidence, not the final benchmark. The 13-case full run remains blocked until independent second review of the labels is complete.
