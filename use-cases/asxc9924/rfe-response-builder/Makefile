.PHONY: install lint test-offline dry-run run

install:
	pip install -e ".[dev]" --break-system-packages

lint:
	ruff check .

test-offline:
	PYTHONPATH=. pytest tests/ -v

dry-run:
	PYTHONPATH=. python -m rfe_response_builder.generate \
		--notice data/sample_rfe_notice.txt \
		--petition data/sample_petition_arguments.json \
		--new-evidence data/sample_new_evidence.json \
		--case-id CASE-2002 --client-name "Marco Alvarez" \
		--out out/ --dry-run

run:
	PYTHONPATH=. python -m rfe_response_builder.generate \
		--notice data/sample_rfe_notice.txt \
		--petition data/sample_petition_arguments.json \
		--new-evidence data/sample_new_evidence.json \
		--case-id CASE-2002 --client-name "Marco Alvarez" \
		--out out/
