# Architecture

## The shape of it

```
            ┌──────────────────────┐          ┌──────────────────────┐
            │  Obsidian plugin     │          │  Headless CLI        │
            │  src/main.ts         │          │  src/cli/index.ts    │
            └──────────┬───────────┘          └──────────┬───────────┘
                       │                                 │
        ObsidianVault  │                       FsVault    │
        obsidianTransport                      nodeTransport
                       │                                 │
                       └──────────────┬──────────────────┘
                                      ▼
                     ┌────────────────────────────────────┐
                     │            src/core                │
                     │  pure · offline · deterministic    │
                     │                                    │
                     │  spine → render → numbering →      │
                     │  assemble → cache diff             │
                     └────────────────┬───────────────────┘
                                      │  assembled HTML
                                      ▼
                     ┌────────────────────────────────────┐
                     │         src/superdocs              │
                     │  client · jobs · figures · passes  │
                     └────────────────┬───────────────────┘
                                      ▼
                             api.superdocs.app
                        export · images · chat · approve
```

Two seams, and both earn their keep.

**`VaultReader`** is the only way core reaches a filesystem. Obsidian implements it with `vault.cachedRead` and `metadataCache.getFirstLinkpathDest`; the CLI implements it with `node:fs` and a path index that mimics Obsidian's shortest-unique-path link resolution; the tests implement it with a `Map`. That is why 131 tests run with no vault, no Obsidian and no disk.

**`Transport`** is the only way the SuperDocs client reaches a network. Obsidian needs `requestUrl` (CORS-free, and the supported path on desktop and mobile alike); Node needs `fetch`; tests need a scripted fake. That is why the HITL flow, the retry policy, the multipart encoder and the pre-signed upload path are all covered without an API key.

---

## The compile pipeline

Eight stages, each timed and reported. Nothing here touches the network.

| Stage | What it does |
|---|---|
| `read-spine` | Read the index note; strip Private Use Area characters at ingest |
| `parse-spine` | YAML frontmatter → book metadata + compile options; body → ordered chapters, parts, regions |
| `bibliography` | Parse the `.bib` file into an entry map |
| `hash-sources` | Hash each chapter plus its recorded transclusions, to decide what can be reused |
| `render` | Per chapter: markdown → **tokenised** HTML. Reused from cache when the hash matches |
| `rehydrate` | Restore reused chapters' figures, footnote bodies, citations and headings from the manifest |
| `injection-scan` | Flag lines that read like instructions aimed at the system |
| `numbering` | One pass over the ordered chapters: assign every number, resolve every token |
| `assemble` | Generated matter + parts + chapters + notes + bibliography, with real page breaks |

### Why tokens

A chapter renders to HTML that still says `⟨fig:north-sheet-4⟩` where `Figure 1.1` belongs. Numbers are assigned once, at assembly, by a pure function over the ordered chapters.

The alternative — resolving numbers during render — makes every chapter's bytes depend on every chapter before it. Add a plate to chapter two and chapter fifty-nine's cached render is invalid, even though not one word of it changed. At 300 pages that is the difference between a recompile that costs milliseconds and one that costs the whole book.

With tokens, the dependency graph is exactly what it should be:

```
chapter bytes  ←  that chapter's source  +  its transclusions  +  its own spine entry
final bytes    ←  chapter bytes  +  the numbering state of everything before it
```

which is what lets the compiler give each chapter one of four verdicts and defend all four:

```
              source hash same?
                 ┌────┴────┐
               yes         no ──────────────► rewritten
                 │
          final bytes same?
             ┌───┴───┐
           yes       no ──────────────────► renumbered
             │
         unchanged
```

`added` and `removed` come from spine membership.

### Why ids are keyed off paths

Every id the compiler emits — chapter anchors, heading anchors, footnote part ids — derives from the note's **path**, never from its position on the spine. `Chapters/02 Ledger.md` becomes `ch-chapters-02-ledger` whether it is chapter two or chapter twenty.

The cost is uglier ids. The benefit is that reordering a manuscript re-renders **nothing**: the numbers move, the prose does not. That is the operation an author performs most often on a long book and the one a naive design punishes hardest.

---

## The manifest

`.manuscript-cache/manifest.json` (in the plugin's data folder, not in the vault tree — a build cache is not a note) holds, per chapter:

```jsonc
{
  "path": "Chapters/01 The Blank Interior.md",
  "sourceHash":  "…",   // source + transclusions + spine entry
  "renderHash":  "…",   // the tokenised HTML
  "resolvedHash":"…",   // what actually landed in the output
  "dependencies": ["Chapters/01 …md", "Shared/Rights Statement.md"],
  "figures": [...], "footnotes": [...], "citations": [...], "headings": [...]
}
```

plus the cached tokenised HTML per chapter and a `sha256 → hosted URL` map for uploaded figures.

Two things this buys beyond speed:

**Resumability.** The manifest is written after every compile. A process killed mid-run leaves a manifest describing the chapters that finished; the next run completes the rest and produces output identical to an uninterrupted run. A test asserts exactly that by deleting entries from a good manifest and re-compiling.

**Correctness for reused chapters.** The full structural metadata is stored, not re-derived. The first design re-parsed cached HTML with regexes and silently lost footnote bodies — those are assembled outside the chapter's own markup, so they were never there to find. Storing them costs manifest size and removes a whole class of bug.

A manifest from an older schema version, or a corrupt one, is **discarded rather than migrated**. A wrong cache is worse than no cache.

---

## Concurrency

Every counter that matters — figure numbering, footnote numbering, citation ordering, anchor allocation — is local to a single `compile()` call. There is no module-level mutable state anywhere in `src/core`. Two compiles of the same vault running at once produce identical, valid output, and a test asserts it by checking that no duplicate `id` attribute appears (which is how shared anchor state would manifest).

The plugin additionally refuses to start a second compile while one is running, because two concurrent writes to the same output file is a different problem and the honest answer there is "wait".

---

## Where money is spent, and where it is not

| Operation | Cost | Why |
|---|---|---|
| Compile (any size) | **0** | Entirely local |
| Export PDF / DOCX / HTML | **0** | Exports are not billable |
| Upload a figure | **0** | And cached by content hash, so it happens once per distinct image |
| Editorial pass | **1** | Opt-in, scoped, confirmed, reviewed |

The whole project — every probe that established the undocumented export conventions, every live export in the README, and both live four-call round trips — consumed **4 operations of a 500/month allowance**.

This is the reason the expensive surface sits behind a preview dialog rather than in the compile path. On a free tier, a tool that discovers its own scope at runtime will find the cap before it finds the bug.

---

## Testing strategy

131 tests, no API key, no network, no disk — plus `npm run scale`, which builds a
60-chapter book on a real filesystem and checks the same properties end to end.

| File | What it holds the line on |
|---|---|
| `compile.test.ts` | Order, generated matter, heading normalisation, numbering, and every one of the "never invents anything" cases |
| `incremental.test.ts` | The four verdicts, byte-equality of untouched chapters, transclusion dependencies, resumption, abort |
| `injection.test.ts` | A document cannot give orders, and cannot forge a numbering token |
| `superdocs.test.ts` | The four calls, the second JSON parse, `awaiting_kind`, per-change rejection, retries, figure upload |
| `units.test.ts` | SHA-256 against FIPS vectors, BibTeX, citation formatting, spine parsing, the diff |
| `scale.test.ts` | 60 chapters / ~90k words: continuity, repeatability, one-chapter edits, concurrency |
| `lifecycle.test.ts` | Aborting mid-compile leaves no partial book; compile requests coalesce instead of being dropped |
| `figures-concurrency.test.ts` | Parallel plate upload stays bounded, cancellable, and still uploads identical bytes exactly once |

Two deliberate choices about what the tests assert:

**Properties, not implementation.** The incremental tests compare the actual bytes of chapters that should not have moved. They would still pass if the caching were rewritten from scratch, and they would fail if it became subtly wrong — which is the opposite of a test that asserts the cache was consulted.

**Every fake failure is loud.** The scripted transport throws when it receives a request it has no reply for, rather than returning a plausible empty object. A mock that silently succeeds is how a mock-only suite ends up proving nothing.
