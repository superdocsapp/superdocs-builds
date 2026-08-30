# SuperDocs agent orchestrator

A multi-agent orchestration layer for SuperDocs: one request from the
document (a selection + a command) fans out to a set of specialist
agents running in parallel, each scoped to one domain, merged back
into a single response by an orchestrator, with a reliability layer
so one agent failing never takes down the rest.

## Why this shape

"World-class AI agent" isn't one giant model â€” it's a small,
well-tested orchestrator plus a roster of narrow specialists, each
independently correct and independently testable. It's also the only
honest way to get to "no lag, no errors": you can't guarantee a model
never errs, but you *can* guarantee that when one does, the system
degrades gracefully and the user never sees a hard failure.

## Agent roster

Four specialist agents are registered in this orchestrator:

- **security_pii** — regex-based detection of emails, phone numbers,
  card-like numbers, and API-key-shaped strings. Fully deterministic,
  with no model dependency.
- **style_tone** — sentence-length, passive-voice, and filler-word
  heuristics, with a seam (`app/llm_client.py`) for future LLM
  refinement.
- **structure_dependency** — explicit v0 analyzer seam for semantic
  structure, dependency, and impact analysis.
- **evidence_factcheck** — explicit v0 analyzer seam for citation,
  provenance, and evidence grounding.

Two additional SuperDocs capabilities are designed for integration
through the same `BaseAgent` interface:

- **redline_compliance** — the existing redline-review engine.
- **translation_localization** — the existing translation-ready-packet
  engine.

The orchestrator therefore provides a common execution, reliability,
and streaming layer for specialist document agents while keeping
each domain implementation independently testable.## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

`POST /agents/run` returns a single merged JSON response.
`POST /agents/stream` returns an SSE stream with one event per agent
as it finishes â€” this is what gives the UI a live, "agents at work"
feel instead of a silent wait behind one spinner.

```bash
curl -X POST http://127.0.0.1:8000/agents/run \
  -H "Content-Type: application/json" \
  -d '{"selected_text": "Contact us at hello@acme.com.", "command": "scan for pii"}'
```

## Test

```bash
pytest
```

24 tests, all passing: agent logic, router matching (including the
"nothing matched, ask everyone" fallback), retry/backoff, circuit
breaker open + recovery, and full FastAPI request/response and SSE
streaming behavior via `TestClient`.

## Extending

Add an agent: subclass `BaseAgent` in `app/agents/`, set `name` and
`triggers`, implement `async def run`. Register it in the
`Orchestrator(agents=[...])` list in `app/main.py`. Nothing else
changes â€” the router, the reliability wrapper, and the streaming
endpoint all work against the `BaseAgent` interface, so adding agent
seven doesn't touch agents one through six.

## Honest v0 status â€” what's not done yet

- Intent routing is keyword-trigger based, not LLM-based. Swap
  `Orchestrator.route` for a classifier call without touching any
  agent â€” the interface is already the seam.
- `structure_dependency` and `evidence_factcheck` are interface
  stubs, not real analyzers.
- No live Gemini/Vertex AI calls â€” `app/llm_client.py` defines the
  interface; `StubLLMClient` is what tests run against. This sandbox
  can't reach Google's API domains, so a real client needs to be
  wired and tested in your own environment.
- No SuperDocs API wiring yet â€” this expects a SuperDocs repo/API to
  call into for applying approved suggestions back to the live
  document; none was available to build against here.
## Credits

Built and engineered by **Vishwak**.