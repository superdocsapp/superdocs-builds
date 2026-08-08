# Fresh clone to working, in one command each.
#
#   make setup    create the venv and install (no key needed)
#   make test     64 tests, no key, no network, 0.04s
#   make demo     the offline demo: verify every saved week, show a diff,
#                 print the measurement. Spends nothing.
#   make replay   re-run the digest driver from committed fixtures, with no
#                 API key and no network. Spends nothing.
#
# The two commands that cost money are called out explicitly and both take a
# hard cap:
#   make scenario   the graded GDD scenario, live      (~6 operations)
#   make run        arm A, up to 20 weeks, resumable  (<=32 operations)
#   make control    the regeneration control arm, live (<=20 operations)
#   make probe      re-check bugs.md B10 against the API (live, 0 operations)

PY := .venv/bin/python
VENV := .venv

.PHONY: setup test demo replay scenario run control probe report verify clean help

help:
	@grep -E '^#( |$$)' Makefile | sed 's/^# \{0,1\}//'

$(VENV):
	@python3 -m venv $(VENV) 2>/dev/null || uv venv $(VENV)

# Works with either a stdlib venv (has pip) or a uv venv (does not). Try pip,
# fall back to uv, and say which one worked instead of leaking a stack trace.
setup: $(VENV)
	@$(PY) -m pip install -q -e ".[dev]" 2>/dev/null && echo "installed with pip" || \
	 (uv pip install -q --python $(PY) -e ".[dev]" && echo "installed with uv")
	@echo "ready. 'make test' needs no API key; 'make scenario' does (see .env.example)."

test: setup
	@$(PY) -m pytest -q

# Everything here reads committed artefacts. No key, no network, no spend.
demo: setup
	@echo "=== every saved week, re-verified from its own bytes ==="
	@$(PY) -m weekly_digest.cli verify
	@echo
	@echo "=== week 13 -> week 14, only the intended changes ==="
	@echo "    (14 is a rollup week: the standing sections turn over AND four"
	@echo "     old archive rows fold into one, inside the same operation)"
	@$(PY) -m weekly_digest.cli diff --week 14
	@echo
	@echo "=== the last graded-scenario result ==="
	@$(PY) -m gdd_editor.cli verify
	@echo
	@echo "=== what the workspace holds ==="
	@$(PY) -m gdd_editor.cli sections

# Replays every recorded call from fixtures/. No key, no network, no spend.
#
# --weeks is COUNTED from the committed artefacts rather than typed. Asking for
# a week that was never recorded is a ReplayMiss by design - correct behaviour,
# but a demo command should not end in one, and a hardcoded number here goes
# stale the first time the run is extended.
replay: setup
	@rm -rf /tmp/superdocs-replay
	@env -u SUPERDOCS_API_KEY $(PY) -m weekly_digest.cli run \
	   --weeks $$(ls weekly-digest/out/arm-a-edit/html/week-*.html | wc -l | tr -d ' ') \
	   --max-ops 200 --out /tmp/superdocs-replay/arm-a
	@echo
	@echo "=== byte-comparing the replay against the committed live run ==="
	@same=0; differ=0; \
	 for f in weekly-digest/out/arm-a-edit/html/week-*.html; do \
	   if cmp -s "$$f" "/tmp/superdocs-replay/arm-a/html/$$(basename $$f)"; \
	     then same=$$((same+1)); \
	     else differ=$$((differ+1)); echo "  DIFFERS: $$(basename $$f)"; fi; \
	 done; \
	 echo "  $$same week(s) byte-identical, $$differ differing"; \
	 test $$differ -eq 0 || exit 1
	@echo "replayed into /tmp/superdocs-replay/arm-a - the committed run was not touched"

# --- these spend operations -------------------------------------------------
scenario: setup
	@$(PY) -m gdd_editor.cli scenario --live --max-ops 14

run: setup
	@$(PY) -m weekly_digest.cli run --weeks 20 --max-ops 32 --live

control: setup
	@$(PY) -m weekly_digest.cli regen --weeks 8 --max-ops 20 --live

# Live but non-billable: uploads, session init and roster reads are all free.
probe: setup
	@$(PY) -m gdd_editor.cli probe-multidoc --live

report: setup
	@$(PY) -m weekly_digest.cli report

verify: setup
	@$(PY) -m weekly_digest.cli verify

clean:
	@rm -rf $(VENV) .pytest_cache **/__pycache__ *.egg-info
