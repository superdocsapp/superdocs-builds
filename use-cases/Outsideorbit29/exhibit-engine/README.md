# Evidence Exhibit Indexer and Cover-Page Engine

A paralegal's tool for an immigration filing. Give it the *brief* and a *pile of
evidence* in mixed formats (PDF, DOCX, TXT, MD, HTML, RTF) and it:

1. **Proposes an exhibit order** that follows the argument in the brief — each
   piece of evidence is placed at the point the brief starts to rely on it.
2. **Generates a numbered cover page** per exhibit describing what it proves.
3. **Builds an exhibit index** whose page ranges *exactly match* the assembled
   packet.
4. **Inserts in-brief citations** (`[See Exhibit N]`) at the sentences that rely
   on each exhibit.
5. **Exports the whole filing as one paginated file** through the SuperDocs API.

**The strong requirement:** adding an exhibit late renumbers the index, the
cover pages, the page ranges, *and* every in-brief citation — together.

Everything is deterministic and works with no API key (the bundled mock server
speaks the same HTTP contract), so it can be tested, demoed and graded offline.
The SuperDocs flow runs the exact four-call contract: **upload → chat with
approval gate → approve → export**.

---

## A filing in the making

![Assembled filing: packet cover, exhibit index and numbered cover pages](screenshot.png)

The start of an exported packet: the filing cover, the exhibit index whose page
ranges match the export exactly, and the first numbered cover pages. The
commands below reproduce it.

---

## Quick start

```bash
# Python 3.10+; install the runtime
pip install -r requirements.txt

# (optional) install the CrewAI cover-writer crew
pip install "crewai>=1.15" "crewai[google-genai]"

# regenerate the synthetic sample filing (all names are fictitious)
python tools/make_sample.py

# run the full engine against the bundled mock SuperDocs server
python -m exhibit.cli run \
    --brief sample/brief/supporting_brief.md \
    --evidence sample/evidence \
    --format html --mock --out packet-out

# after installing (pip install -e .), the same command is just:
exhibit-engine run --brief ... --evidence ... --mock --out packet-out
```

Outputs in `packet-out/`:

- `packet.html` — the **assembled filing**: packet cover, exhibit index, and one
  numbered cover page + content pages per exhibit. Page numbers in the index
  match this file exactly.
- `brief-with-citations.html` — the **edited brief** with `[See Exhibit N]`
  markers spliced in at the sentences that rely on each exhibit.

### Adding an exhibit late

```bash
exhibit-engine run \
    --brief sample/brief/supporting_brief.md \
    --evidence sample/evidence \
    --add-late sample/late/medical_report.txt:3 \
    --format html --mock --out packet-out
```

Inserting `medical_report.txt` after exhibit 3 renumbers the covers, the index,
the page ranges *and* every in-brief citation to match — one command, no
drift.

### Live run against the real SuperDocs API

```bash
export SUPERDOCS_API_KEY=sk_...      # from your dashboard; never commit it
exhibit-engine run --brief sample/brief/supporting_brief.md \
    --evidence sample/evidence --format pdf --live --out packet-out
```

No key in the environment? The CLI also reads the dashboard API key saved to
`~/.superdocs/personal_key.txt` (create one at use.superdocs.app → Settings →
API Keys; the key never touches the transcript):

```bash
# one line, just the key:  sk_...
echo sk_... > ~/.superdocs/personal_key.txt
exhibit-engine run --brief sample/brief/supporting_brief.md \
    --evidence sample/evidence --format html --live --out packet-out
```

(An agent-account variant existed via `tools/superdocs_login.py`, but SuperDocs
keeps agent accounts on their own free tier and won't merge them into an
existing human account, so live runs use the human account's key and credits.)

`--live` drives the real API (the approval gate asks you to approve each
proposed change); `--mock` drives the bundled fake. Both run the identical
four-call contract (upload → chat → approve → export). The live export is the
**edited brief with in-brief citations** — the model inserts each `[See Exhibit N
(Title), which evidences …]` marker at the sentence that relies on it, with the
real names, dates, amounts and numbers (the proposal is fictional sample data).
Cover pages, exhibit contents and the index are assembled deterministically by
the engine into `packet.html`, whose page ranges match the index by construction
— the model is never asked to invent layout, only to mark the brief.

---

## How it stays consistent

The whole point of an exhibit index is that its page ranges tell you where to
find each exhibit *in the finished filing* — so pagination has a hard invariant:

> the page ranges printed in the index MUST equal the pages the assembled
> packet actually occupies.

That is kept **by construction**: `paging.paginate_set` is the single place page
numbers are assigned, and `paging.render_packet` renders exactly the same layout
it assigned. The index length uses one shared formula (`index_page_count`), so
the front matter can never disagree with the rendered index pages.

Citations are **computed from the set**, never stored against fixed numbers, so
any mutation (late insert, remove) re-derives everything that depends on
position. The 42-test suite locks this down (`tests/`):

- `test_paging.py` — index page ranges equal rendered packet pages.
- `test_renumber.py` — late insert renumbers covers, index, citations, pages.
- `test_citations.py` — anchors land on the sentence that relies on the exhibit.
- `test_order.py` — evidence order follows the brief's argument.
- `test_superdocs_client.py` + `test_flow.py` — the four-call HTTP contract.
- `test_loader.py` — mixed-format evidence extraction.
- `test_covers.py` — cover-page text is grammatical and grounded in the exhibit
  (a regression guard on the deterministic cover writer).

## How ordering and citations work

Each exhibit is scored against every brief sentence. Its **filename title** is
the strong signal (a topic keyword counts 10×), its **body text** the weak one
(1×), and proper nouns are excluded so names never drive matching. Every exhibit
is anchored at its best-scoring sentence; two exhibits may genuinely rely on the
same sentence ("...joint bank accounts and a joint tax return...") and each gets
its citation. Exhibit order = the order the brief relies on them; evidence no
brief sentence touches is appended last, never dropped.

## Optional CrewAI cover writer

By default cover-page text ("what it proves") is produced deterministically from
the exhibit's own content. When a CrewAI crew is available (`crewai` installed
and a `GEMINI_API_KEY`/`GOOGLE_API_KEY`/`OPENAI_API_KEY`/`ANTHROPIC_API_KEY` set),
the CoverWriter agent authors that text instead. The deterministic fallback
always works, so the engine never requires an LLM.

```bash
# copy .env.example -> .env and add GEMINI_API_KEY, then:
export GEMINI_API_KEY=...
exhibit-engine run --brief ... --evidence ... --mock --out packet-out
```

## Layout

```
exhibit/
  cli.py        command line (run, --mock/--live, --add-late)
  flow.py       the SuperDocs four-call filing flow
  superdocs.py  SuperDocs API client (upload/chat/approve/export)
  mock_server.py in-memory SuperDocs fake for offline testing
  proposals.py  the analyst: order + cover text + paginate + cite
  order.py      evidence ordering that follows the brief's argument
  citations.py  sentence scoring + in-brief citation planning/apply
  covers.py     numbered cover pages (what it proves)
  index.py      exhibit index with page ranges
  paging.py     deterministic pagination (single source of truth)
  loader.py     mixed-format evidence extraction
  model.py      Exhibit / ExhibitSet / PaginatedPacket
  crew.py       optional CrewAI OrderPlanner + CoverWriter crew
tests/          42 tests (mock server, no key required)
tools/make_sample.py  regenerates the synthetic sample filing
sample/         synthetic brief + mixed-format evidence pile
```

## Data & privacy

Everything in `sample/` is synthetic and fictitious (the "Sharma" family spousal
visa filing) — no real client data, no confidential material, no real documents.
Never put real evidence in the repo; real client files belong outside it.

---

*Built by Anish Kumar for the SuperDocs Round 2 task.*
