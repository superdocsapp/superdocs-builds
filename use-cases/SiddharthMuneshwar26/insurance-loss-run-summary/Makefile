.PHONY: install corpus test dry live clean
install:
	pip install -r requirements.txt
corpus:
	cd corpus && python generate.py
test:
	python -m pytest tests/ -q
dry:
	python -m lossrun.review --corpus corpus/out --out out --mode dry --max-ops 6 --as-of 2026-01-09
live:
	python -m lossrun.review --corpus corpus/out --out out --mode live --max-ops 6 --as-of 2026-01-09
clean:
	rm -rf out .pytest_cache **/__pycache__
