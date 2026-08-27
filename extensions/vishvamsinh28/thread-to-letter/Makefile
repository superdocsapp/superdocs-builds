# Thread to letter.
#
# One rule across both of this repository's builds:
#   live     — talks to api.superdocs.app. Uses your key. Costs operations.
#   offline  — talks to a local stand-in. No key, no network, no cost.
.PHONY: help live offline cli addon test sync clean

help:
	@echo "  live      — the demo: a mail client with the add-on in it, real API (2 ops)"
	@echo "  offline   — the same pipeline in the terminal, local stand-in (no key, no cost)"
	@echo ""
	@echo "  cli       — one thread from the terminal, live (2 ops)"
	@echo "  addon     — the Apps Script add-on's own code, live (2 ops)"
	@echo "  test      — the full suite, offline"
	@echo ""
	@echo "  sync      — regenerate the add-on's prompts from the Python source"
	@echo "  clean     — remove local output"

live:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@uv run thread2letter doctor
	@echo ""
	@echo "\033[1mLIVE\033[0m — open http://127.0.0.1:8430 and click a thread."
	@echo "\033[2mIt spends nothing until you press a button. One op to find, one to write.\033[0m"
	@echo ""
	@uv run thread2letter serve --port 8430

offline:
	@echo "\033[2mOFFLINE — local stand-in, no key, no cost.\033[0m\n"
	@./scripts/demo.sh

cli:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@echo "\033[1mLIVE\033[0m — 2 operations.\n"
	@uv run thread2letter run threads/migration-project.mbox --from "you@example.com"

addon:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@echo "\033[1mLIVE\033[0m — runs gmail-addon/Code.gs unmodified. 2 operations.\n"
	@node gmail-addon/simulate.js threads/migration-project.mbox

test:
	@uv run pytest

sync:
	@uv run python scripts/sync_prompts.py

clean:
	@rm -rf out out-nothing .pytest_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "cleaned"
