PYTHON ?= python3
VENV_PYTHON := .venv/bin/python

ifneq ("$(wildcard $(VENV_PYTHON))","")
PYTHON := $(VENV_PYTHON)
endif

.PHONY: demo test metrics scale-manual frontend-build frontend-test run check

demo:
	$(PYTHON) scripts/review_demo.py

test:
	$(PYTHON) -m pytest -q

metrics:
	$(PYTHON) scripts/metrics.py

scale-manual:
	$(PYTHON) scripts/generate_scale_manual.py fixtures/scale-manual-400-pages.pdf --pages 400

frontend-build:
	npm --prefix frontend run build

frontend-test: frontend-build
	npm --prefix frontend test -- --run
	cd frontend && npx playwright test

run: frontend-build
	$(PYTHON) -m uvicorn linecard.api:app --host 127.0.0.1 --port 8877

check: test frontend-test
