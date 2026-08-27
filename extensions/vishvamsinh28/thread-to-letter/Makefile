.PHONY: help demo offline cli addon test sync clean

help:
	@echo "make demo    — the demo: a mail client, the add-on panel, the real API"
	@echo "make offline — the same pipeline in the terminal, no key, no cost"
	@echo "make cli     — run it on a thread from the terminal, live (2 ops)"
	@echo "make addon   — run the Apps Script add-on's own code, live (2 ops)"
	@echo "make test    — the full suite, no key needed"
	@echo "make sync    — regenerate the add-on's prompts from the Python source"
	@echo "make clean   — remove local output"

# The demo. A simulated inbox, the add-on panel on the right, real SuperDocs calls.
demo:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@uv run thread2letter doctor
	@echo ""
	@echo "  Open http://127.0.0.1:8430 and click a thread."
	@echo "  It spends nothing until you press a button."
	@echo ""
	@uv run thread2letter serve --port 8430

offline:
	@./scripts/demo.sh

cli:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
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
