# LineCard handoff

## Status

LineCard is ready to run and review locally. Its verified capabilities include
the reviewer UI, evidence selection, 400-page scale check, deterministic
two-page card verification, PDF generation, and safety-first export gating.

The live M1 proposal-approval completion remains intentionally blocked by a
documented SuperDocs provider defect: proposal `chunk_id` values have no direct
owner in the authoritative `document_sync.content` HTML. No fuzzy matching,
provider approval, or provider export is allowed while that condition remains.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
cd frontend && npm ci && cd ..
make check
make run
```

Open `http://127.0.0.1:8877`.

## Verified handoff checks

- Python tests: 61 passed.
- Frontend build and unit tests: passed.
- Browser workflow: 3 passed, including evidence selection, blocked/restored
  export, the 400-page scale check, and safety-gap preview state.
- No live M1 approval or export was submitted during corrected verification.

## Reviewer starting points

- [README](../README.md) — product overview and setup.
- [Demo script](demo-script.md) — three-minute walkthrough.
- [Live M1 bug report](superdocs-live-bug-report.md) — exact limitation and
  safe reproduction.
- [Acceptance ledger](acceptance-ledger.md) — verified versus blocked gates.
