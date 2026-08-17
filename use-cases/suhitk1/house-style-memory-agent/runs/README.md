# Run artefacts

One directory per experiment run. Each holds `h3_cache.json` (the content-hash
cache for the one model-scored rule), `run_manifest.json` (pinned rubric,
template and prompt versions), and the raw per-document scores. All of it is
committed: the H3 cache in particular is what makes correction determinism
verifiable after the fact, so preflight refuses to start a run whose cache
would not be published.
