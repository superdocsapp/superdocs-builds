# Longhaul. Everything below runs offline: no API key, no network, no cost.
.PHONY: help live console demo test proof lint mcp clean

help:
	@echo "make live    — the console, against the real SuperDocs API (needs .env)"
	@echo "make console — the same console, against the local stand-in (no key, no cost)"
	@echo "make demo    — run a job, kill it, resume it, diff the result"
	@echo "make test    — the full suite, 20+ kill points included"
	@echo "make proof   — kill and resume at EVERY checkpoint a run reaches"
	@echo "make mcp     — how to wire the MCP server into an agent"
	@echo "make clean   — remove local state and exports"

demo:
	@./scripts/demo.sh

test:
	@PROOF_SAMPLE=24 uv run pytest

# The headline claim, unsampled. Writes the raw per-kill-point data to docs/.
proof:
	@PROOF_ARTIFACT=docs/proof-results.json uv run pytest tests/test_kill_points.py -s

lint:
	@uv run python -m compileall -q src tests && echo "ok"

live:
	@./scripts/live.sh

console:
	@./scripts/console.sh

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
