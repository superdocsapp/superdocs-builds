.PHONY: help demo live test sync clean

help:
	@echo "make live  — run the pipeline against the real SuperDocs API (needs .env, 2 ops)"
	@echo "make demo  — the same pipeline against a local stand-in (no key, no cost)"
	@echo "make test  — the full suite, no key needed"
	@echo "make sync  — regenerate the add-on's prompts from the Python source"
	@echo "make clean — remove local output"

demo:
	@./scripts/demo.sh

live:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@uv run thread2letter doctor
	@echo ""
	@uv run thread2letter run threads/migration-project.mbox --from "you@example.com"

test:
	@uv run pytest

sync:
	@uv run python scripts/sync_prompts.py

clean:
	@rm -rf out out-nothing .pytest_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "cleaned"
