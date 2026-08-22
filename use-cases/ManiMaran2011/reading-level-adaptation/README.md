# Reading-Level & Curriculum Adaptation Engine

SuperDocs Round 2, Task 2 — assigned build (S2): takes a course chapter and produces adapted versions —
lower reading level, a language-learner version with a glossary sidebar, a reduced-load version, and a
version aligned to different curriculum terminology — while figures, equations, and captions survive
byte-identical and only the prose changes. Includes a comparison view and handles source revisions without
discarding teacher edits already made to an adaptation.

Built on SuperDocs' REST API (`/v1/documents/upload`, `/v1/chat`, `/v1/documents/export`) using the
`data-chunk-id` structural editing surface — every paragraph, heading, table, and cell SuperDocs parses out
gets a stable id, which is the mechanism this build depends on for "figures and equations survive
byte-identical": adaptation instructions are scoped to prose chunks only, and every protected chunk's HTML is
hash-verified unchanged after each adaptation run, not just trusted.

## How it works

1. **Upload + classify.** The source chapter is uploaded via `/v1/documents/upload`. Each returned chunk is
   classified as `protected` (figures, equations, tables containing numeric/formula content, captions) or
   `prose` (everything else) using a rule-based classifier — see `src/chunk_classifier.py` — deliberately
   simple and inspectable rather than another LLM call, since getting this classification wrong is exactly
   what would let a figure get silently rewritten.
2. **Adapt.** For each of the four adaptation types, a dedicated SuperDocs session is opened against the
   SAME uploaded document, and a scoped chat instruction is sent: "adjust the reading level of the prose
   sections only; do not modify [list of protected chunk ids]." SuperDocs' own targeted-chunk editing means
   this is a real constraint, not just a polite request — but it's still verified, not trusted (next step).
3. **Verify.** After each adaptation, every protected chunk's HTML in the adapted version is hashed and
   compared against the source's hash for that same chunk id. Any mismatch is a **detected, surfaced
   failure** — the build doesn't silently accept a broken adaptation, it reports which chunk broke and lets
   the caller decide (retry scoped tighter, or flag for human review). This is the "detects and surfaces
   them, never graded on whether the numbers were right" bar from the task card, taken literally.
4. **Glossary (language-learner version only).** Vocabulary terms are extracted from the ACTUAL adapted
   prose text via a scoped chat instruction ("list domain vocabulary actually used in this text, with a
   plain-language definition grounded in how the text uses it") — not a generic word list. See
   `src/glossary.py`.
5. **Comparison view.** `src/comparison.py` builds a chunk-aligned side-by-side view: for every chunk id
   present in the source, show the source text next to each adaptation's text for that same chunk, with
   protected chunks visually marked "unchanged" (backed by the hash check, not a visual guess).
6. **Regeneration on source revision.** `src/revision.py` diffs the revised source's chunks against the
   previous source's chunks by id+hash. Only chunks whose source content actually changed get re-adapted.
   Chunks a teacher has since hand-edited in an adaptation are tracked in a `locked_chunk_ids` set (passed in
   by the caller — the actual "was this teacher-edited" bookkeeping belongs to whatever app calls this
   engine) and are skipped even if their source changed, until the caller explicitly unlocks them.

## What's tested without a live key

`tests/` runs entirely against `FakeSuperDocsClient` (see `src/fake_client.py`) — a scripted stand-in with
the same interface as the real client, mirroring the same pattern used in Task 1's `FakeLLM`. Covered:
- Protected chunks (equation, table, figure caption) are verified byte-identical after adaptation, and a
  simulated corruption is correctly detected and reported rather than silently passed.
- Prose-only chunks are the only ones sent for adaptation.
- Regeneration after a source revision only re-adapts chunks whose source hash changed, and skips locked
  (teacher-edited) chunks even when their source changed.
- Glossary extraction is scoped to a chat call over the adapted text, not a static list.

**Not yet run against the real API** — that needs an actual `sk_` key (see `.env.example`) and real chapter
content sent through `/v1/documents/upload` → `/v1/chat` → `/v1/documents/export`. The demo video is where
that gets proven for real; `python -m src.cli demo` runs the same flow against the real client once
`SUPERDOCS_API_KEY` is set.

## What's honestly a gap

- Curriculum-terminology alignment (the fourth adaptation type) currently uses a single free-text
  terminology-mapping instruction rather than a structured glossary-of-equivalents input; a real deployment
  would want the terminology map as structured data the caller supplies, not prose the model has to parse.
- The chunk classifier is heuristic (looks for `<table>`, patterns like "Equation", "Figure", numeric-heavy
  short paragraphs). It will misclassify some edge cases — a prose paragraph that happens to quote a formula
  inline, for instance. Logged rather than hidden; the fallback when uncertain is to protect (never risk
  silently mangling something that might be a figure/equation).

## Real bug found running against the live API (2026-08-22)

Running the CLI against the real SuperDocs API (not the fake client) surfaced real problems the fake
client's tests couldn't have caught, because the fake client didn't reproduce SuperDocs' actual behavior:

1. **Chunk ids are not stable across a chat turn.** SuperDocs reassigns `data-chunk-id` values when it
   processes a document — even for content it didn't touch. **Fixed:** verification and the comparison view
   match protected content by a whitespace-normalized, id-stripped content hash, not by id.
2. **The classifier's "short italic text is probably a caption" rule was too broad.** Narrowed to require
   the text to actually mention figure/table/diagram/chart/photo/image.
3. **The most significant finding: natural-language "do not touch these chunks" instructions are not
   reliably honored, even when the exact protected chunk ids are listed explicitly in the prompt.** Across
   every live run, the model rewrote Figure 4.1's caption wording despite being told character-for-character
   not to. This isn't a prompting failure that better wording fixes — SuperDocs' chat surface is natural-
   language-driven ("the AI handles all internal section lookups"), and it doesn't expose a hard,
   enforceable "never touch this element" constraint at the API level.

   **The real fix wasn't a better prompt — it was not depending on the prompt at all.**
   `repair_protected_chunks()` splices each protected chunk's ORIGINAL content back into the adapted
   document at its aligned position, unconditionally, after every adaptation. Byte-identical preservation
   is now a property of this code, not a property of the model's compliance. Verification runs on the
   *repaired* output and reports success only if the repair actually landed everywhere it needed to (it can
   still honestly fail if the model deletes an entire section so there's no position left to repair into —
   that's a real, surfaced failure, not swept aside).

   `tests/test_repair.py` reproduces the exact real-world corruption (id reassignment + reworded caption,
   copied from an actual failed live run) and proves the repaired output is byte-identical to source while
   leaving legitimate prose simplifications untouched.

This is the single most important design decision in this build, and it only came from running against the
real product instead of stopping at the fake-client test suite: **"detects and surfaces" was the original,
weaker design (refuse to export, tell the human why). "Enforces regardless of model behavior" is the
stronger one this became**, after live evidence showed the weaker design would refuse to ever export
successfully at all.

4. **A second, more subtle bug found immediately after fixing #3: the repair never actually reached the
   exported file.** `run_adaptation()` correctly repairs content in `result.html`, and verification correctly
   passes — but `export()` pulls the document from SuperDocs' SERVER-SIDE session state, not from Python's
   local `result.html`. Nothing was syncing the repair back to the server, so every export silently
   contained the AI's original, uncorrected content despite "OK — all protected chunks byte-identical"
   printing to the terminal. **Fixed:** `client.load_html_as_document()` (wrapping
   `/v1/documents/upload-base64` with `parse_mode='document'`, the documented verbatim-replace path) is now
   called with the repaired html immediately before every export. `tests/test_export_sync.py` reproduces
   this exact failure mode and pins the fix.
5. **Reusing the same deterministic `session_id` across repeated runs caused content to accumulate.**
   Testing this build meant running the CLI against the same file multiple times while debugging; every run
   used the same session id, and the exported document ended up containing several differently-worded
   copies of the whole chapter concatenated together — evidence that resending `document_html` to an
   already-populated session doesn't reliably behave as a full replace in practice, whatever the intended
   semantics. **Fixed:** the CLI now mints a fresh, unique session id per invocation (timestamp-suffixed),
   so repeated runs never collide.
