# Gmail thread → formal letter

Built by **Mekala Kaveri** for the SuperDocs task.

**Kind:** open list (kind 2). Card: *Gmail add-on: thread to formal letter*. Host app would be Gmail; this demo takes a Gmail-shaped JSON export because we are not shipping a Workspace add-in. SuperDocs still does upload, chat, approve, export. Not a SuperDocs clone.

**Who:** deal-desk or in-house counsel who must write “what did we actually promise” from a messy thread. Fictional parties: Northwind / Acme.

**Strong look (from the card):** extract actual commitments, do not summarise politely. “Soon” / “maybe” / “try to” are not dates. The sample thread commits to a redlined MSA by **Thursday 28 August 2026**.

```bash
cd use-cases/MekalaKaveri18/gmail-thread-letter
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app:app --host 127.0.0.1 --port 8792
pytest -q
```

Open http://127.0.0.1:8792/

SuperDocs: templates, chat, approve, export. Credit: built for the SuperDocs task.
