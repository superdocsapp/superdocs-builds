.PHONY: install test dry sample live clean
install:
	pip install -r requirements.txt
test:
	python -m pytest tests/ -q
dry:
	python -m tablebench.run --mode dry --max-ops 25 --out results
sample:
	python -m tablebench.run --mode dry --limit 3 --max-ops 3 --out results
live:
	python -m tablebench.run --mode live --max-ops 25 --out results
clean:
	rm -rf results corpus_out .pytest_cache **/__pycache__
