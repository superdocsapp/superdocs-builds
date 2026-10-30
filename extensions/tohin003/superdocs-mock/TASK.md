# TASK.md — how to work in this repository

Read this before changing anything. It is the working contract for humans and agents alike.

## What this is

An offline test double for SuperDocs. It replays recorded API responses so an integrator's CI
can run the full upload → edit → review → export loop over REST *or* MCP with no key, no
quota and no flake — plus a contract suite that runs the same assertions against the mock and
against the live service, to prove the two still agree.

It is built **on** SuperDocs, never a copy of it. It has no document engine and cannot edit
anything. That boundary is not negotiable.

## The order of work

Always, for anything non-trivial:

1. **Write the behaviour down** in `docs/behaviours.md` with the source it came from.
2. **Write the test** in `contract/`, naming the `B-ID`.
3. **Then** write the code that makes it pass.

A behaviour with no source citation does not go in the ledger. A shape I "remember" is not a
source — `spec/openapi.json` and a docs URL are.

## Rules that never bend

- **No secrets, ever.** Not in a file, a fixture, a log line, a commit message, or history.
  The key lives at `~/.config/superdocs/api-key`, mode 600, outside every repository. Examples
  use `SUPERDOCS_API_KEY=your-key-here`.
- **No real content.** Every document in `corpus/` is fabricated. Companies, names, figures
  and addresses are invented. Nothing recorded here belongs to anyone.
- **No guessing.** If two sources disagree, it goes in `docs/findings.md` as **VERIFY** and is
  settled against the live service before anything claims it.
- **No silent fiction.** A missing cassette degrades to a spec-generated stub that says, in
  the response, that it is synthesised. It never impersonates a recording.
- **Determinism is a feature.** No wall-clock, no unseeded randomness, no unordered JSON in
  any response path. If a value varies between runs, it is a bug.
- **Nothing outside my folder.** When this lands in `superdocs-builds`, the diff touches
  `extensions/tohin003/superdocs-mock/` and nothing else.

## Spending operations

Recording against the live service costs money on someone's quota.

- Phase 1 budget: **50 billable operations**, hard stop.
- Log every live call in `PROGRESS.md` with its `usage` block.
- Uploads, parses, exports, `whoami`, `get_account_status` and `request_limit_increase` are
  free — prefer them for probing.
- Anything that loops gets a stopping rule before it gets a first run.
- A quiet screen for 30 s to several minutes is the API still working. Do not resend; retries
  spend operations.

## Verifying my own work

The implementer does not get to be the verifier. Before a phase is called done, a fresh pass
re-reads the exit criteria against the artifacts and tries to falsify each one. "It should
work" closes nothing.

## Layout

| Path | What lives there |
|---|---|
| `spec/` | Pinned published surface — never hand-edited |
| `docs/behaviours.md` | The ledger. The specification of this mock |
| `docs/findings.md` | Divergences found in SuperDocs, verified before reporting |
| `corpus/` | Fabricated source documents |
| `cassettes/` | Recorded scenarios — the deliverable |
| `src/sdmock/` | The mock: replay core, REST routes, MCP server, recorder |
| `contract/` | The contract suite — the other deliverable |
| `PROGRESS.md` | Running log of decisions, assumptions and live calls |
