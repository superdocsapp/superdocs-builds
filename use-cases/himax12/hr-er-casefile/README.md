# Employee-relations letter engine (SuperDocs Task 2)

Assigned build: **HR / ER specialist** handling conduct and performance.

The app issues improvement plans, absence letters, invitations to hearing, outcome letters, and appeal responses **in order**. If you try to skip a step, it refuses and explains why. Meeting notes feed the outcome letter; the employee's words are copied **verbatim**, never paraphrased. A case-file document keeps the chronology.

Fictional demo person: Jordan Hale (no real HR files).

## How to run

```bash
cd use-cases/himax12/hr-er-casefile
python -m pip install fastapi uvicorn pytest
python -m pytest -q
uvicorn er_engine.api:app --reload
```

Environment: `SUPERDOCS_API_KEY=your-key-here` only if you wire the live four calls. Tests use a fake upload → chat → approve → export client and do not spend operations.

Small-sample mode is on by default on the fake client (stops after three chat calls) so a loop cannot burn quota.

## SuperDocs surfaces

- **Templates** — markdown templates in `templates/` (PIP, absence, invite, outcome, appeal, case file).
- **Chat / review / export** — `er_engine/superdocs_flow.py` implements the four-call contract (upload, chat, approve, export). Proposed-change `content` that arrives as a JSON string is parsed **twice**.
- **Multi-document** — case file plus each letter is its own document id in one case.

Live SuperDocs wiring is the same four endpoints as the docs; keep the key out of git.

## Sequence (cannot skip)

1. Open case  
2. PIP and/or absence letter (after open)  
3. Meeting notes (with verbatim employee speech)  
4. Invitation to hearing  
5. Hearing notes  
6. Outcome letter (verbatim block required)  
7. Appeal response  

## Credit

Built for the SuperDocs engineering task by the operator of GitHub `himax12`.
