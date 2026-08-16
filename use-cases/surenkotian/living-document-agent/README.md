# Living-document agent

Built by Suren Kotian for the SuperDocs Founding Engineer task.

An agent that owns one named section of a standing SuperDocs document -- "**[AGENT-MAINTAINED] Live Service Status**" -- and keeps it current from a changing external source, without ever touching the human-written sections around it. Everything below was run against the real SuperDocs API with a real (free-tier) account; nothing here is mocked.

## What it does

The standing document, "Team Operations Dashboard", has three sections:

- **Weekly Priorities** -- human-written, static
- **Team Notes** -- human-written, static
- **[AGENT-MAINTAINED] Live Service Status** -- owned by this agent, regenerated from `source_data/*.json` (standing in for a real monitoring feed)

Every run:

1. Hashes the current source file.
2. **Unchanged since the last run → stop. Zero API calls.** This is the stopping rule, and it's also what makes the agent structurally incapable of re-triggering on its own output: it only ever reacts to the *external source* changing, never to the document changing, so its own edit can never look like new work to itself.
3. Changed, with `--preview` → fetch the current document (a free read) and print what *would* change. No `chat` call, no approval, no cost.
4. Changed, live → propose the update via `chat_async(approval_mode="ask_every_time")`, refuse to approve anything that touches a chunk outside the owned section, and after approval **independently re-fetch the document and hash-compare every chunk outside the section against a snapshot taken before the edit**. If anything else moved, that's a hard failure -- logged loudly, not swallowed.

## Surfaces used

- **MCP-equivalent (REST)** -- the task doc states anything specified against the REST API may be built on MCP and vice versa; this build uses the REST surface (`/v1/chat`, `/v1/chat/async`, `/v1/chat/{session}/approve`, `/v1/documents/{id}`), which exposes the identical four core operations MCP does.
- **Review** -- every ongoing update goes through `chat_async` + `approve_change`, SuperDocs' own human-in-the-loop mechanism, not a direct sync edit.
- **Search** -- the owned section is re-located every run by searching the document's own structure for its heading text (`locate_owned_section` in `living_doc_agent.py`), rather than trusting a remembered chunk_id blindly. A manually reorganized document is still found correctly.
- **Memory** -- not used in the shipped version; see "What I'd add next" below for why, honestly, rather than bolted on for the sake of touching the surface.

## Proving the ownership boundary is never crossed

`chunking.py` parses the document's real HTML into its top-level `data-chunk-id` blocks (verified against real API output, not assumed from docs). Before every edit, every chunk **outside** the owned section is hashed. After the edit, they're hashed again. If they don't match byte-for-byte, the run fails loudly. This isn't a claim -- it's `assert before_snapshot == after_snapshot` against real data fetched from the live API, both times.

## Real proof run (not a description)

Full transcript in `PROOF_RUN.md`. Summary, with real numbers from the account's own `whoami`:

| Step | Source | ops before -> after | Result |
|---|---|---|---|
| Bootstrap | `status_v1.json` | 2 -> 3 | Document created, owned section = 2 chunks (heading + table) |
| Update | `status_v2.json` (Auth Service degrades) | 3 -> 6 | Table updated in place; **5 other chunks byte-identical before/after** |
| Re-run, same source | `status_v2.json` | 6 -> 6 | **Zero API calls** -- stopping rule, proven via `whoami`, not asserted |
| Update | `status_v3_recovered.json` (recovery) | 6 -> 7 | Table updated again; boundary check passed again |
| Preview | `status_v2.json` (after already applying v3) | 7 -> 7 | Diff printed, **zero cost**, confirmed via `whoami` |

`agent_state.json`'s `run_history` (also in `PROOF_RUN.md`) reads `created -> updated -> noop -> updated` -- a readable history, not four full-document rewrites.

A PDF export of the final live document is at `team_operations_dashboard_final.pdf` (exports don't cost operations).

## A real bug, found and fixed, not papered over

The first live update revealed a genuine design flaw. The original instruction said "replace the table **and the Last synced line**" -- two separate things, one a table cell, one a standalone paragraph. The model didn't edit the old paragraph in place; it **inserted a new paragraph** with the fresh timestamp and left the stale one sitting there, orphaned, without even a `data-chunk-id`. Two "Last synced" lines, one of them dead. Exactly the "churn instead of a readable history" failure this build is supposed to prevent.

Fix: folded the timestamp **into the table** as a spanning final row, so there is exactly one dynamic element to replace, not two things to keep in sync. "Replace this whole table with an updated table" turned out to be unambiguous in a way "also update that line somewhere below" wasn't. Re-ran clean afterward -- see the second row of the table above. Full detail in `PROOF_RUN.md`.

Separately, the post-hoc boundary-diff comparison itself had a bug: it only checked chunks that existed in *both* the before and after snapshot, so a chunk that got **added** outside the owned section (exactly what the paragraph-duplication bug produced) wouldn't have been caught by the diff logic as a "changed" chunk. Fixed to check added/removed/changed separately. Both bugs are logged here because they were both real, found by actually running this against the live API, not by reasoning about the code.

## What I'd add next, honestly

- **Cross-session memory** wasn't used in the end. I considered writing agent-preference notes into SuperDocs' `cross_session_memory` so the agent could recall its own maintenance conventions across sessions with no local state at all. Decided against it for this submission: the local `agent_state.json` (chunk IDs, last source hash, run history) is the thing that actually has to be correct for the boundary guarantee, and duplicating that into a second, server-side, less-inspectable store would have added a real state-reconciliation problem (which one wins if they disagree?) without making the core guarantee any stronger. Worth doing for a version that needs to survive losing `agent_state.json` entirely.
- The pre-approval boundary check (reject a proposed change before it's even approved, if it targets an out-of-scope chunk) is implemented and exercised by the code path, but never actually triggered in this proof run because the model's proposed changes stayed correctly scoped every time -- so it's real code, live-key-testable, but not yet caught a live violation. The post-hoc check (which did catch the paragraph-duplication issue) is the one with a real save.

## Running it

```bash
python -m venv .venv && source .venv/Scripts/activate   # or .venv/bin/activate on Mac/Linux
pip install -r requirements.txt
cp .env.example .env   # fill in SUPERDOCS_API_KEY (agent self-signup: POST /v1/agents/signup)

python living_doc_agent.py --source source_data/status_v1.json                    # bootstrap
python living_doc_agent.py --source source_data/status_v2.json --preview          # no-spend preview
python living_doc_agent.py --source source_data/status_v2.json --auto-approve     # live update
python living_doc_agent.py --source source_data/status_v2.json --auto-approve     # no-op (same source)
```

Omit `--auto-approve` to review each proposed change interactively before it lands.
