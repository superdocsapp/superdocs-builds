# Progress & engineering notes

My working log for this build: what it does, the calls I made, and where I decided to stop.

## What this is

A Notion ⇄ Word review-cycle round-trip, built on the SuperDocs API. A team keeps its source of
truth in Notion; its formal reviewers work in Microsoft Word. This sends a Notion page out as a
styled Word document, reads the reviewer's tracked changes and comments when it comes back,
proposes each change through SuperDocs, and lands the approved ones on the exact Notion block —
preserving structure and reviewer attribution throughout.

## Status

Complete, and proven end to end on both the deterministic providers and the live services.
**164 tests that need no API key**, plus a Postgres-backed store test; `ruff`, `mypy --strict` and
`pytest` all green. I verified the one-command claim by cloning the repository fresh, with no
`.env`: `make check` and `make demo` both run unchanged.

I have driven the full cycle live on real Notion pages many times. Tracked changes and AI-authored
comment edits landed on the right blocks; a rejected change left its block untouched; a second
round editing the same blocks was refused by the drift guard rather than overwriting the first; and
a returned document was picked up and applied with nobody at a terminal.

Two live runs are worth naming because they are the claims most easily asserted and not shown:

- **The whole handoff inside Notion.** A request row, the styled `.docx` attached to it by the
  service, the marked-up copy dropped back onto the same row, approval in the Notion queue, and the
  block updated — one operation, no folder and no terminal anywhere in the loop.
- **Multi-document.** Two real Notion pages sent as one packet: a single export containing both, a
  reviewer change on each, and each change written back to its own page. One operation.

## Architecture

- **Two provider seams behind typed protocols** — a Notion client and a SuperDocs client — each
  with a deterministic in-memory implementation for the keyless suite and demo, and a live HTTP
  implementation. Selection is one config flag.
- **Outbound**: fetch each page's block tree → render to HTML preserving structure (headings,
  lists, to-dos, toggles, callouts, tables, code, inline databases) and rich text, recording a
  reversible block map → upload the whole document to SuperDocs → export a styled `.docx` → stamp
  the review-round id into it → record the round and link it on the page.
- **Inbound**: parse the returned `.docx`'s tracked changes and comments from raw OOXML → match
  each change to its block → propose it through SuperDocs in review mode → **human gate** → write
  approved changes back to Notion, block by block.
- **SuperDocs does the editing, not me.** A tracked change goes out as a scoped edit; a directive
  comment is handed to SuperDocs' AI, which *authors* the concrete edit and returns it with an
  explanation. All four contract calls are exercised: upload, chat, approve, export.
- **One headless gate, three drivers**: a review queue *in Notion*, a comment on the changed line
  itself, and a terminal gate for a script or an agent. Decisions from any of them are merged.
- **Boards are discovered, not configured.** Every *Review requests* database shared with the
  integration is served. Notion's search returns only what someone shared with the connection,
  so sharing a board switches a team on and unsharing switches it off; no id is ever configured,
  and a board shared while the service runs is picked up within a minute.
- **The whole cycle runs unattended, and stays inside Notion.** A button writes a request row; the
  styled document is attached to that row; reviewers put their marked-up copies back on it; each is
  matched by the id it carries, proposed, and queued; the owner's decisions are read back and
  applied. Folders are the same pair of seams with a different implementation.
- **Intake is per submission, not per round.** A review goes to several reviewers and comes back as
  several files, so a returned copy is identified by a hash of its contents and proposed on its own
  graph thread, merging into the round's one set of proposals and its one queue.
- **Durable execution**: the inbound review is a LangGraph graph with a checkpointer and a real
  interrupt at the gate, so a run survives a crash or a days-long pause and resumes where it
  stopped.
- **Persistence**: each round is a row in a store behind a protocol — SQLite by default, Postgres
  for scale — with an optimistic version, so concurrent work is rejected rather than lost. The
  store and the graph checkpoint live under a mounted `data/` directory: the service runs in a
  throwaway container, and a review that survives a restart is the whole point of checkpointing.

## Decisions

- **LangGraph with a checkpointer for the inbound flow.** The review is a long-lived, human-gated
  process, and durable execution with an interrupt gate is the right primitive for it. A dedicated
  workflow engine is the scale path once volume warrants it.
- **SuperDocs is the only metered call.** Orchestration is deterministic code, so cost is
  centralised and auditable, and the whole test suite and demo run for free on the fakes.
- **I built on the REST API rather than MCP.** The card names API as a surface and the brief treats
  the two as interchangeable; REST was the shorter path to the four calls. An MCP surface over the
  same controller is a natural addition, not a rewrite.
- **Write-back is per-block, verified by read-back, and surgical.** Only blocks a reviewer changed
  are touched; a change is marked applied only after the block is re-read and confirmed; the edit
  is spliced in so surrounding formatting survives.
- **A drifted block is a conflict, not a clobber.** If the page changed while it was out for
  review, the change is surfaced for a human instead of overwriting the newer edit.
- **Approval is an operation, not a screen.** The controller exposes it and the interface is a
  driver — which is why the same gate runs from Notion, from a comment thread, and from a terminal.
- **The returned file carries its own round id**, so any return channel works without a human
  quoting an identifier.
- **Idempotency wherever an operation costs money.** Each change carries a content hash, so a
  re-run after a crash re-spends nothing and double-applies nothing.
- **The `.docx` is untrusted input**: read behind zip-bomb and XXE defenses, reviewer text
  sanitised before it reaches the AI, links surfaced at the gate, and a size cap at the write.

## Assumptions I logged along the way

Where the brief or the API was silent, I made a call and recorded it.

1. **A SuperDocs session holds one pending proposal set at a time.** I verified this live: with
   proposals pending, a second chat on that session returns `409 session_busy` and never clears.
   So a review larger than one operation goes out batch by batch, each gated and applied before
   the next — which is also the card's "one approval at a time".
2. **`approve` keys each change on `change_id`, not `chunk_id`.** The documentation says
   otherwise, and approving by `chunk_id` returns a 500. I reverse-engineered the real contract
   and verified it against the live API.
3. **One operation per request that changed something**, when the API returns no usage block.
   Otherwise a per-round budget could never trip. This follows the documented billing rule.
4. **A reviewer's question is not an edit request.** A comment ending in "?" goes to the page owner
   rather than to the AI, which could otherwise fabricate an answer into the document. The
   heuristic is deliberately conservative and the human gate is the backstop.
5. **Decisions are polled, not pushed.** Polling suits a review measured in hours or days, keeps
   this to one moving part, and leaves no public endpoint to expose.
6. **Reviewer attribution is provenance, not authenticated identity.** Word author names are
   self-declared strings; I report them faithfully and claim nothing more.
7. **Delivery and intake are one decision, never configured apart.** A channel that can send but
   not receive is a promise the round-trip cannot keep, so the factory returns both halves together.
   The default keeps them on the Notion request row; folders are the other implementation, real
   when synced to a shared drive. I deliberately did not ship an email sender without an email
   intake, for the same reason.
8. **A returned file is identified by its contents, not by its round.** Every reviewer marks up
   their own copy and they all carry the same round id, so keying intake on the round would mean
   the first copy back silently stood for all of them. The same file twice is a duplicate that
   costs nothing; a different file is another reviewer.
9. **A copy that arrives while changes are still at the gate waits its turn.** A SuperDocs session
   holds one pending proposal set at a time — the same limit the batch loop exists for — so the
   file is left where it is and taken in on the pass that clears the gate. Nothing is set aside.
10. **Competing changes are named, never resolved.** Only one rewrite of a line can land and the
    drift guard refuses the rest, which was already safe but silent. The owner is now told which
    changes compete before deciding; the system still does not choose between reviewers.
11. **Notion's button block is the trigger.** It cannot be created through the public API, but a
    person can add one pointed at the requests database, which is what makes the whole cycle a
    single click without the integration pretending to something the API does not offer.
12. **An empty proposal set is a failure, not an answer.** A chat can finish reporting no error
    and propose nothing at all. Believed, it silently demotes every AI-authored edit in the
    batch to a plain note — which is exactly what happened on a live round. We only ask when we
    have concrete changes in hand, so nothing back is re-submitted under the same bounded retry.
13. **SuperDocs' `approve` is one call per job.** Approving closes the job, and a second call
    for the rest of that job's changes is refused with *"Job is not awaiting approval"*. An
    owner deciding a queue over hours is the normal case, so a job's decisions are held until
    every change it proposed has been decided, then sent once. Verified live.
14. **Which boards to serve is a fact about the workspace, not the deployment.** Configuring a
    database id would mean editing an environment file and restarting a service every time a
    team started using this — which is not a shape that survives production. Notion's search
    returns exactly what has been shared with the connection, so discovery is both the right
    answer and the one the API was already offering. The search matches loosely and also
    returns our own per-round review queues, so only an exact title counts as a board.

## Accepted inputs

- **Documents**: a Notion page — or several as one review packet — goes out; a reviewer's Word
  `.docx` with tracked changes and comments comes back. A second run means different Notion pages
  and different reviewer markup within that shape.
- **Structures carried across the round-trip**: headings, paragraphs, quotes, bulleted and numbered
  lists, to-dos, code, callouts, tables, and inline databases. A toggle's *contents* survive; its
  title does not, because SuperDocs drops the summary on upload.

## Limitations

- **One workspace per deployment.** A single Notion integration token rather than per-workspace
  OAuth; multi-tenancy is not built.
- **An outside reviewer still needs sending the file.** Inside the workspace the loop is
  hands-free. For a reviewer with no Notion access the owner forwards the document from the row and
  puts the reply back on it — one human hop, which email would close.
- **The SQLite store is single-writer.** It deliberately does not use write-ahead logging:
  WAL keeps committed rows in a side file coordinated through shared memory, and that
  coordination is not reliable on the bind mounts this runs on — a second connection can
  conclude it is the last one and delete the side file out from under a live writer. Postgres
  is the backend for anything that wants more than one process.
- **Notion caps an attachment at 5 MiB on a free workspace.** Prose pages export far below it; a
  very large document would need the folder channel.
- **Two reviewers editing one paragraph in the same file** are merged by Word into a single
  resulting text, attributed to the first author. Separate copies keep attribution exact.
- **Table cells cannot be targeted individually.** SuperDocs re-chunks a whole table as one unit on
  upload, so an edit aimed at a single cell cannot be isolated back to that cell. It is surfaced
  rather than guessed at.
- **A toggle's summary text is dropped by SuperDocs on upload**, so a toggle title has no chunk
  to reconcile against and an edit to one cannot round-trip. `unmapped_blocks` is therefore
  expected on any page holding a toggle; the log names which blocks and why. This and the table
  limitation above are both SuperDocs-side, and reported as bugs.
- **Decisions apply within one poll interval** (fifteen seconds by default), not instantly.
- **No notifications**: the page is commented and updated, but nobody is emailed.

## Running it

```bash
make check           # ruff + mypy (strict) + the full keyless test suite
make demo            # the whole round-trip on the fake providers — no keys, no operations
make test-postgres   # the store against a real Postgres
```

For a live run, copy `.env.example` to `.env` and add the SuperDocs and Notion keys. `.env` is
git-ignored, no secret is committed, and every log line is scrubbed of tokens before it is emitted.
`notion-review status` is where I look first when something needs investigating: it shows every
round, what became of each change, why anything failed, and the ids to trace it through both
services.

## What I would build next

- Email as a channel, both directions at once — the third implementation of the seams that the
  Notion-row and folder channels already share, and what closes the last hop to an outside reviewer.
- Per-workspace OAuth and multi-tenancy.
- A guided three-way merge: drift is detected and surfaced today; reconciling a reviewer's edit
  against newer Notion text is the next step.
- An MCP surface, so another agent can drive the same gate the CLI drives.
