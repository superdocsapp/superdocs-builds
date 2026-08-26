# Clause library, fallback ladder, and drift audit

*Built by Arun S for the SuperDocs Round-2 task.* (Open-list family: **RAG, templates and benchmark**.)

A firm's **approved clauses live in a library** (data). A drafter searches it in plain language and
gets the **preferred clause plus its fallback ladder**; a second command **audits a whole document**
and flags every clause that has **drifted** from the library. Search is semantic (embeddings), not
keyword; the audit produces a **reviewable list, never a rewrite**. The chosen clause is inserted
into the document through **SuperDocs**, adapting party names and numbering to the host document.

```
plain-language query --embed--> nearest topic --> preferred clause + fallback ladder
whole document       --embed--> per-topic match --> aligned / drifted / missing (a review list)
chosen clause        --------> SuperDocs (adapt + insert) --> .docx
```

## Run it (fully offline, no key)
```bash
python run_demo.py                         # search + ladder + drift audit on the samples
python run_demo.py "cap on liability for damages"
python -m pytest tests/ -q                 # 5 keyless tests
```
Example audit of `sample_contract.txt`:
```
OK  aligned  limitation_of_liability      sim=0.95   (copied verbatim from the library)
OK  aligned  termination_for_convenience  sim=0.88
~~  drifted  confidentiality              sim=0.45   (reworded "secrecy" clause)
XX  missing  governing_law                sim=0.35   (no such clause in the draft)
```

## Files
| File | What it is |
|---|---|
| `library.py` | The core: `find` (query → topic + ladder), `search`, `ladder`, `audit` (aligned/drifted/missing). |
| `embed.py` | Deterministic hashing embedder + cosine — keyless; the neural/pgvector seam drops in behind it. |
| `superdocs_min.py` | The SuperDocs hand-off — `insert_clause` (adapt + insert) + export. |
| `sample_library.json` | The approved clauses (preferred + fallback ladders) for 4 topics. |
| `sample_contract.txt` | A draft with one aligned, one drifted, and one missing clause. |
| `run_demo.py` | Offline demo. |
| `tests/` | 5 keyless tests: paraphrase search, ladder order, audit classification, insert/export. |

## What "strong looks like" — and the honest limit
- **Ladder + drift audit:** fully delivered and tested — the audit is a review list, not a rewrite, and
  library updates take effect immediately (it's data, no reinstall).
- **Semantic search:** the keyless embedder is **lexical**, so it matches queries that share key terms
  ("cap on liability and damages" → limitation of liability) but **not** queries with *zero* shared words
  ("how much would we owe if we mess up"). True synonym matching is the **neural-embedder seam**: swap a
  model + pgvector behind `embed()` and the interface is unchanged. The demo prints a *low-confidence*
  note when a query has no lexical overlap, rather than pretending it matched.

## Where this goes
A pull request into the public repository, **use-cases** folder. Secrets stay out of the code
(the SuperDocs key comes from the environment); add a screenshot before opening the PR.
