.PHONY: install test-offline run

install:
	pip install -r requirements.txt --break-system-packages

test-offline:
	PYTHONPATH=. pytest tests/ -v

run:
	PYTHONPATH=. python -m case_status_desk.generate --cases data/sample_cases.json --out out/
