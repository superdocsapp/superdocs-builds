# TASK.md — how to work on docs-lint

This file is for whoever (human or agent) picks up this codebase next. It says how to work here,
not what the project does. That is `README.md`.

## The one rule

`check` never writes to a file. `fix` never writes to a file without a recorded human decision.

Everything else in this codebase is negotiable. That is not. If a change makes it possible for a
correction to land on disk without passing through a `Decisions` object, the change is wrong,
regardless of how convenient it is.

## Order of work for anything hard

1. Write down what the system must **never** do.
2. Write the test that proves it does not.
3. Then write the code.

This order is not ceremony. The three genuinely hard parts here — resuming a killed run, two runs at
once, and a document that tries to give the linter orders — are all things where the failure is
silent. A test written after the fact tends to test what the code does rather than what it should do.

## Running things

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'

pytest                    # full suite, no API key needed, no operations spent
pytest -m resume          # kill/restart behavior
pytest -m concurrency     # two runs at once
pytest -m injection       # hostile document fixtures
pytest -m live            # deselected by default; needs SUPERDOCS_API_KEY, spends operations
ruff check . && ruff format --check .
```

The suite must stay green with `SUPERDOCS_API_KEY` unset. That is a load-bearing claim in the
README — anyone should be able to verify what this thing says about itself without paying for it.
If a test starts needing a live key, it is either mismarked or badly designed.

## Test doubles

`tests/fake_superdocs/` is a real HTTP server implementing the SuperDocs endpoints this project
uses, with injectable failures and latency. Tests point `SUPERDOCS_BASE_URL` at it.

It exists because mocking the client object proves only that the mock works. The brief for this
round says so explicitly, and it is right. Drive the real client over real HTTP against a fake
server, so the client's own request construction, retry logic and parsing are under test.

`tests/fixtures/cassettes/` holds responses recorded from the live API. When the fake and a
cassette disagree, the cassette wins — it is what the real service actually sent.

## Logging assumptions

Anything ambiguous gets a dated entry in `PROGRESS.md` with the call made and the reasoning. Do not
stop and wait for an answer on an ambiguity you can reasonably resolve; resolve it, log it, keep
going.

## Things that will bite you

- Proposed-change content from the API arrives as a JSON-encoded **string** and needs a second
  parse. The final result is already an object. Skipping the second parse yields diff cards where
  every field reads `undefined`.
- Operations on large documents can take minutes with no visible progress. That is still processing,
  not a crash. Poll, do not assume.
- Exports and downloads do not cost operations. Searches do. Budget accordingly.
