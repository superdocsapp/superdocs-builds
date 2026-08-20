# Guidewire / Duck Creek policy-doc app

Built by **Mekala Kaveri** for the SuperDocs task.

Insurance carriers running Guidewire or Duck Creek still export PAS data and format endorsements by hand. This app takes a **fictional PAS JSON** (policy number, named insured, coverage lines, endorsement effective date), fills a wording template, optionally polishes it through SuperDocs, then exports.

## Strong path

POST the sample in `fixtures/sample-policy.json`. The generated document must show **both coverage lines** (CGL and BPP) and **2026-09-01** in the endorsement clause and insuring agreement. That merge is tested without a live key.

## How to run

```bash
cd use-cases/MekalaKaveri18/pas-policy-docs
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy ..\.env.example ..\.env
uvicorn app:app --reload --host 127.0.0.1 --port 8788
```

Open http://127.0.0.1:8788/

## Tests (no live key)

```bash
pytest -q
```

## SuperDocs surfaces

API (PAS JSON in), templates, chat + HITL approve, export. Four-call contract: upload template/document, chat, approve, export.

Credit: built for the SuperDocs task.
