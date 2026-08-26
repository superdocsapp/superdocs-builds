# SuperDocs Integration Sizing Guide

Derived directly from the latency/throughput results in this run. Numbers below are p50/p95 wall-clock seconds per phase, not averages -- plan for the tail, not the median.

## large document, concurrency=1
- **upload**: p50=4.43s, p95=4.68s, p99=4.71s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=7.67s, p95=9.11s, p99=9.20s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=3.72s, p95=4.55s, p99=4.71s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.89s, p95=1.10s, p99=1.14s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~16.70s typical, ~19.45s worst-observed-case

## large document, concurrency=2
- **upload**: p50=6.78s, p95=7.20s, p99=7.24s (n=2 ok, 0 rate-limited [0%], 3 errored)
- **processing**: p50=12.17s, p95=15.46s, p99=15.75s (n=2 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=4.21s, p95=4.21s, p99=4.21s (n=1 ok, 0 rate-limited [0%], 1 errored)
- **export**: p50=1.20s, p95=1.20s, p99=1.20s (n=1 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~24.36s typical, ~28.07s worst-observed-case

## large document, concurrency=4
- **upload**: no successful samples (0 rate-limited, 5 errored) -- all 5 cycles failed with local DNS resolution errors (getaddrinfo failed), not SuperDocs API errors. See README "Real results" section.
- **processing**: no successful samples (0 rate-limited, 0 errored)
- **editing**: no successful samples (0 rate-limited, 0 errored)
- **export**: no successful samples (0 rate-limited, 0 errored)
- **End-to-end**: no data -- see README for why

## large document, concurrency=8
- **upload**: no successful samples (0 rate-limited, 5 errored) -- same local DNS resolution issue as concurrency=4, worse at higher concurrency (more simultaneous lookups)
- **processing**: no successful samples (0 rate-limited, 0 errored)
- **editing**: no successful samples (0 rate-limited, 0 errored)
- **export**: no successful samples (0 rate-limited, 0 errored)
- **End-to-end**: no data -- see README for why

## medium document, concurrency=1
- **upload**: p50=1.92s, p95=2.56s, p99=2.64s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=4.15s, p95=5.97s, p99=6.30s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=1.42s, p95=2.38s, p99=2.44s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.64s, p95=0.85s, p99=0.86s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~8.13s typical, ~11.76s worst-observed-case

## medium document, concurrency=2
- **upload**: p50=2.12s, p95=3.16s, p99=3.21s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=6.10s, p95=9.34s, p99=9.61s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=2.53s, p95=2.96s, p99=2.96s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.83s, p95=0.99s, p99=1.02s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~11.59s typical, ~16.44s worst-observed-case

## medium document, concurrency=4
- **upload**: p50=2.85s, p95=3.46s, p99=3.50s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=8.84s, p95=17.63s, p99=18.55s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=3.07s, p95=4.09s, p99=4.18s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.79s, p95=0.99s, p99=1.00s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~15.56s typical, ~26.17s worst-observed-case

## medium document, concurrency=8
- **upload**: p50=4.18s, p95=5.00s, p99=5.05s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=9.43s, p95=10.02s, p99=10.05s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=4.73s, p95=5.36s, p99=5.49s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=1.02s, p95=1.53s, p99=1.63s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~19.36s typical, ~21.92s worst-observed-case

## small document, concurrency=1
- **upload**: p50=1.00s, p95=2.05s, p99=2.25s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=4.44s, p95=12.12s, p99=13.56s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=1.60s, p95=2.03s, p99=2.09s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.73s, p95=0.79s, p99=0.80s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~7.77s typical, ~16.99s worst-observed-case

## small document, concurrency=2
- **upload**: p50=1.10s, p95=1.31s, p99=1.31s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=5.32s, p95=10.90s, p99=11.91s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=1.40s, p95=1.57s, p99=1.60s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.74s, p95=0.75s, p99=0.76s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~8.56s typical, ~14.54s worst-observed-case

## small document, concurrency=4
- **upload**: p50=5.06s, p95=5.13s, p99=5.14s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=4.56s, p95=7.37s, p99=7.66s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=2.54s, p95=2.59s, p99=2.59s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=1.36s, p95=1.38s, p99=1.39s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~13.52s typical, ~16.47s worst-observed-case

## small document, concurrency=8
- **upload**: p50=2.15s, p95=2.16s, p99=2.16s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **processing**: p50=5.92s, p95=7.11s, p99=7.15s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **editing**: p50=2.38s, p95=2.49s, p99=2.49s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **export**: p50=0.75s, p95=1.03s, p99=1.04s (n=5 ok, 0 rate-limited [0%], 0 errored)
- **End-to-end (sum of phase p50/p95)**: ~11.20s typical, ~12.78s worst-observed-case

## Reading this
- If your integration is interactive (a human waiting on a review UI), budget for the p95 end-to-end number, not p50 -- roughly 1 in 20 requests will be at or beyond it.
- If a cell shows a non-trivial rate-limited fraction, that concurrency level exceeds what the current plan tier sustains; either lower concurrency or budget for backoff/retry time in addition to the latencies above.
- The `large` tier at concurrency 4 and 8 has no data due to a local DNS resolution issue on the benchmark-running machine, not a SuperDocs API limitation. See the main README's "Real results" section for the full explanation and root cause.
