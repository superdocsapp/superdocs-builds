.PHONY: bootstrap run test demo demo-scenario demo-scenario-2 mcp frontend-install frontend-dev frontend-build

bootstrap:
	bash scripts/bootstrap.sh

run:
	PYTHONPATH=. uvicorn app.api.main:app --reload

test:
	PYTHONPATH=. pytest tests/ -v

demo:
	PYTHONPATH=. python3 scripts/demo.py

demo-scenario:
	PYTHONPATH=. python3 scripts/demo_scenario.py

# A second, genuinely different document batch (different vendor, mix,
# and label formats) run through the unmodified pipeline -- proves the
# "works the second time, on different documents" requirement rather
# than asserting it.
demo-scenario-2:
	PYTHONPATH=. python3 scripts/demo_scenario_2.py

mcp:
	PYTHONPATH=. python3 scripts/mcp_client_probe.py

# Review console (frontend/). `make run` (backend) + `make frontend-dev`
# gives you the full stack: open the printed Vite URL, then POST to
# /demo/seed (or use the "Load Meridian demo scenario" button on an
# empty Dashboard) to see real documents move through classification,
# review, and metadata write-back.
frontend-install:
	cd frontend && npm install

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build
