# Plot spine

Built by **Mekala Kaveri** for the SuperDocs task.

**Kind:** original invention. Not a SuperDocs clone. Aimed at people who actually lose plotlines in long manuscripts.

**Industry:** trade fiction. **Users:** acquiring / continuity editors on a Tor-like list, and indie novelists who hire Reedsy editors. The job: keep a thousand-page book coherent while SuperDocs edits *one scene*.

A plot bible is configuration (characters, deaths, bearings). Chapter 12 of the sample tries to resurrect Mara Vale and to order the system to ignore continuity — that is data, not a command. Repair touches chapter 12 only; chapters 3 and 8 keep the same hash.

```bash
cd use-cases/MekalaKaveri18/plot-spine
pip install -r requirements.txt
uvicorn app:app --host 127.0.0.1 --port 8790
```

http://127.0.0.1:8790/ · `pytest -q` (no live key)

SuperDocs: upload/template, HITL chat, export. Credit: built for the SuperDocs task.
