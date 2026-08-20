#!/usr/bin/env bash
set -eu
test -f pyproject.toml
test -f docs/acceptance-ledger.md
python3 -m venv .venv
.venv/bin/pip install -e '.[test]'
(cd frontend && npm ci && cd .. && make check)
git diff --check
echo FRESH_CLONE_CHECK_PASS
