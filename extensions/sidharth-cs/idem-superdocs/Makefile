.DEFAULT_GOAL := help
.PHONY: help setup test test-py test-ts typecheck audit audit-py audit-ts fuzz smoke clean

help:  ## Show this help
	@echo "Idempotency and safe-retry middleware — quick start:"
	@echo "    make setup && make test"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup:  ## Create a venv and install the one dev dependency (pytest)
	python3 -m venv .venv
	./.venv/bin/pip install -q --upgrade pip
	./.venv/bin/pip install -q -e "python[dev]"
	@echo "Ready. The library itself has no runtime dependencies."

test: test-py test-ts  ## Run both implementations against the same vectors

test-py:  ## Python suite — no network, no API key
	cd python && ../.venv/bin/python -m pytest -q

test-ts:  ## TypeScript suite — same vectors.json, no network, no API key
	cd typescript && node --test --experimental-strip-types --no-warnings "tests/*.test.ts"

typecheck:  ## Type-check the TypeScript implementation
	cd typescript && npx --yes typescript@5.9 tsc --noEmit

audit: audit-py audit-ts  ## Mutation-test both suites: inject bugs, check they are caught

audit-py:  ## Inject 12 bugs into the Python source, confirm the suite catches them
	python3 python/scripts/mutation_audit.py

audit-ts:  ## Same 12 bugs against the TypeScript source
	python3 typescript/mutation_audit.py

fuzz:  ## Randomised fault injection, turned up (override IDEM_FUZZ_RUNS / IDEM_FUZZ_SEED)
	cd python && IDEM_FUZZ_RUNS=$${IDEM_FUZZ_RUNS:-5000} ../.venv/bin/python -m pytest tests/test_fuzz.py -q

# Some Python builds ship without a CA bundle. Use the system one when it is
# there, so `make smoke` works without the caller knowing this exists.
CA_BUNDLE := $(firstword $(wildcard /etc/ssl/cert.pem /etc/ssl/certs/ca-certificates.crt))

smoke:  ## OPTIONAL live run against the real API. Spends metered operations.
	@echo "This spends real SuperDocs operations, capped at IDEM_SMOKE_MAX_OPERATIONS."
	cd python && $(if $(CA_BUNDLE),SSL_CERT_FILE=$(CA_BUNDLE)) ../.venv/bin/python scripts/smoke_live.py

clean:
	rm -rf .venv python/.pytest_cache python/**/__pycache__ typescript/node_modules
