# Hashlock

Built by **Mekala Kaveri** for the SuperDocs task.

**Kind:** original extra. Not a SuperDocs clone. SuperDocs still does upload, chat, approve, and export. This app only prints a SHA-256 receipt for sections marked `data-lock="true"`.

**Who:** anyone who must prove a clause did not move (legal ops, PAS forms, vendor MSAs). The brief grades proof over assertion. Hashlock is that sentence as a tool.

| Button | Expected verdict |
|---|---|
| Tighten | **PASS** — unlocked service paragraph changes; parties / governing law / liability hashes hold |
| Tamper a lock | **FAIL** — parties clause mutated on purpose. Fail closed is the demo |

```bash
cd use-cases/MekalaKaveri18/hashlock
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app:app --host 127.0.0.1 --port 8791
pytest -q
```

Open http://127.0.0.1:8791/

Without a key, **Tighten** and **Tamper** run offline (no billed call). With `SUPERDOCS_API_KEY` in the sibling `.env`, Tighten goes through SuperDocs HITL; the receipt is computed on the HTML that comes back.

SuperDocs: templates, chat, approve, export. Credit: built for the SuperDocs task.
