.PHONY: help test-offline test-db evidence evidence-offline evidence-db test-frontend test-all

TEST_DATABASE_URL ?= postgresql+asyncpg://postgres:postgres@localhost:5432/bates_packet_test

help:
	@echo "Bates Exhibit & Privilege Packet Builder - Make Targets"
	@echo ""
	@echo "Offline Targets (No DB, No API Key):"
	@echo "  make test-offline       - Run 86 offline unit, safety, and ingestion tests (DEBUG=false)"
	@echo "  make evidence-offline   - Run 39 offline evidence and benchmark evaluation tests (DEBUG=false)"
	@echo "  make test-frontend      - Run Vitest component tests and TypeScript typecheck"
	@echo ""
	@echo "Database-Backed Targets (Requires PostgreSQL):"
	@echo "  make test-db            - Run full 307 backend tests against TEST_DATABASE_URL"
	@echo "  make evidence-db        - Run 71 DB-backed evaluation, kill-matrix, and evidence tests"
	@echo "  make evidence           - Run offline evidence (or evidence-offline + evidence-db)"
	@echo "  make test-all           - Run complete suite (offline, db, frontend)"

test-offline:
	@echo "Running offline keyless evidence and unit tests (no DB required)..."
	cd backend && DEBUG=false pytest \
		app/tests/test_evidence_redaction_residue.py \
		app/tests/test_content_descriptions.py \
		app/tests/test_safety_rejection.py \
		app/tests/test_offline_bates_resume.py \
		app/tests/test_offline_redaction_verify.py \
		app/tests/test_offline_state_machine.py \
		app/tests/test_ingestion.py \
		app/tests/test_superdocs_adapter.py \
		app/tests/test_evaluation.py \
		-v

evidence-offline:
	@echo "Running offline evidence and benchmark evaluation tests (no DB required)..."
	cd backend && DEBUG=false pytest \
		app/tests/test_evaluation.py \
		app/tests/test_evidence_redaction_residue.py \
		app/tests/test_safety_rejection.py \
		app/tests/test_offline_bates_resume.py \
		app/tests/test_offline_redaction_verify.py \
		-v

evidence-db:
	@echo "Running DB-backed evidence & kill matrix against $(TEST_DATABASE_URL)..."
	cd backend && DEBUG=false TEST_DATABASE_URL="$(TEST_DATABASE_URL)" pytest \
		app/tests/test_evidence_crash_recovery.py \
		app/tests/test_evidence_manifest_reconciliation.py \
		app/tests/test_evidence_zero_double_stamping.py \
		app/tests/test_superdocs_integration_evidence.py \
		app/tests/evaluation/ \
		app/tests/test_ocr_search.py \
		-v

evidence: evidence-offline

test-db:
	@echo "Running full backend test suite against $(TEST_DATABASE_URL)..."
	cd backend && DEBUG=false TEST_DATABASE_URL="$(TEST_DATABASE_URL)" pytest -v

test-frontend:
	@echo "Running frontend tests and typecheck..."
	cd frontend && npm test -- --run && npx tsc --noEmit

test-all: test-offline test-db test-frontend
	@echo "All tests completed successfully."

