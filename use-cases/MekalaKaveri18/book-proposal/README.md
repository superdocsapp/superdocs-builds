# Book proposal with market section

Built by **Mekala Kaveri** for the SuperDocs task.

Assembles a non-fiction book proposal for authors: comparable titles, audience, and chapter outline. Comparable titles come from a catalog of **specific real books** (author, year, publisher, ISBN) — not “similar titles in the category.” SuperDocs does not browse the live web; search runs on that catalog, then SuperDocs fills a stored proposal template and you export.

## How to run

```bash
cd use-cases/MekalaKaveri18/book-proposal
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env   # then put SUPERDOCS_API_KEY=your-key-here
uvicorn app:app --reload --host 127.0.0.1 --port 8787
```

Open http://127.0.0.1:8787/

Without a key the app still runs in **offline sample** mode (no billed SuperDocs call). With a key it uploads the template, starts a HITL chat job (`upload` → `chat/async` → `approve` → `export`).

## Tests (no live key)

```bash
pytest -q
```

## SuperDocs surfaces

search (catalog + instruction to use only those comps), templates (`/v1/templates/upload`), chat + HITL approve, export.

Credit: built for the SuperDocs task.
