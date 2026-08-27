.PHONY: help console demo live addon test sync clean

help:
	@echo "make console — the review console in a browser (needs .env)"
	@echo "make live  — the same pipeline on the terminal (needs .env, 2 ops)"
	@echo "make demo  — the same pipeline against a local stand-in (no key, no cost)"
	@echo "make addon — run the Gmail add-on's own code against the live API (2 ops)"
	@echo "make test  — the full suite, no key needed"
	@echo "make sync  — regenerate the add-on's prompts from the Python source"
	@echo "make clean — remove local output"

demo:
	@./scripts/demo.sh

console:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@uv run thread2letter doctor
	@echo ""
	@uv run thread2letter serve --port 8430

live:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@uv run thread2letter doctor
	@echo ""
	@uv run thread2letter run threads/migration-project.mbox --from "you@example.com"

addon:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@node gmail-addon/simulate.js threads/migration-project.mbox

test:
	@uv run pytest

sync:
	@uv run python scripts/sync_prompts.py

clean:
	@rm -rf out out-nothing .pytest_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "cleaned"
