# Longhaul.
#
# One rule across both of this repository's builds:
#   live     — talks to api.superdocs.app. Uses your key. Costs operations.
#   offline  — talks to a local stand-in. No key, no network, no cost.
.PHONY: help live offline proof proof-all test lint mcp clean

help:
	@echo "  live      — the operator console, against the real API (needs .env, spends)"
	@echo "  offline   — the same console, against a local stand-in (no key, no cost)"
	@echo ""
	@echo "  proof     — kill a run and resume it, diff the result. ~6s, offline"
	@echo "  proof-all — the same at EVERY checkpoint a run reaches. ~95s, offline"
	@echo "  test      — the full suite, offline"
	@echo ""
	@echo "  mcp       — how to wire the MCP server into an agent"
	@echo "  clean     — remove local state and exports"

live:
	@test -f .env || { echo "No .env — copy .env.example and add your key."; exit 2; }
	@echo "\033[1mLIVE\033[0m — api.superdocs.app. Opens idle; spends nothing until you press Run.\n"
	@./scripts/live.sh

offline:
	@echo "\033[2mOFFLINE — local stand-in, no key, no cost.\033[0m\n"
	@./scripts/console.sh

# One kill point, start to finish, in a few seconds.
proof:
	@echo "\033[2mOFFLINE — determinism is only provable against a fixed backend.\033[0m\n"
	@./scripts/demo.sh

# Every checkpoint a real run traverses.
proof-all:
	@echo "\033[2mOFFLINE — 119 kill points, each a real SIGKILL.\033[0m\n"
	@PROOF_ARTIFACT=docs/proof-results.json uv run pytest tests/test_kill_points.py -s

test:
	@PROOF_SAMPLE=24 uv run pytest

lint:
	@uv run python -m compileall -q src tests && echo "ok"

mcp:
	@echo 'Add this to your MCP client config:'
	@echo ''
	@echo '  "longhaul": {'
	@echo '    "command": "uv",'
	@echo '    "args": ["run", "--directory", "$(PWD)", "longhaul-mcp",'
	@echo '             "--spec", "jobs/runbook-migration.yaml"],'
	@echo '    "env": { "SUPERDOCS_API_KEY": "sk_your_key_here" }'
	@echo '  }'

clean:
	@rm -rf state out .fake-state demo-state .pytest_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
	@echo "cleaned"
