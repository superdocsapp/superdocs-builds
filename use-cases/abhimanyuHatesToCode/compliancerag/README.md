# King's Council 👑

> *Three ministers walk into a throne room. Each has a proposal. The king needs to know who's lying.*

That's the demo. The real thing underneath is a production-grade RAG compliance auditing pipeline — one that ingests documents, retrieves evidence, evaluates governance rules, detects cross-document conflicts, and routes every non-compliant finding through SuperDocs for human approval before anything gets decided.

The kingdom is a costume. The engine is the point.

---

## What it does

A session loads four documents — one rule book (ground truth) and three minister amendment proposals. For each of ten governance rules, the pipeline retrieves evidence across all four documents, evaluates compliance, and flags conflicts where ministers contradict each other or the rule book. Every non-compliant finding becomes a real SuperDocs edit, pending the king's decision.

**Five stages, no magic:**

- **Ingest** — documents chunked, embedded via `all-MiniLM-L6-v2`, indexed into FAISS + BM25
- **Retrieve** — hybrid BM25 + FAISS retrieval fused via Reciprocal Rank Fusion
- **Evaluate** — Gemini 2.5 Flash evaluates each rule against retrieved evidence, returns `compliant` / `non_compliant` / `needs_review`
- **Conflict detect** — pairwise LLM comparison across sources for non-compliant findings only
- **Review** — every finding routed through SuperDocs; approval or rejection is final

---

## Why a King's Council ?

The answer is simple, I don't want to pretend I know everything about the policies, all the doctrines and acts written. Try to be performative and telling why GDPR is violating DPDP Act, why Northgate's disciplinary policies are better than that of Meridian College. So I just sat down and thought why not make something lucid, and familiar, somethiing that can be explained, and also involves the person who's actually trying to understand. The project is domain agnostic — the same pipeline that audits a king's treasury can audit a GDPR compliance report. That's not a claim, that's just how it's built.

Therefore I went for the King's Council, because I believe honesty beats theatre everywhere ;)


---

## SuperDocs is not a wrapper here

Every `non_compliant` finding produces a real SuperDocs document edit with a specific suggested fix. The king approving or rejecting that finding *is* the SuperDocs human-in-the-loop gate — not a formatting step at the end, not a summary export. The pipeline is blocked until every finding has a decision. Only then does the final governance brief export.

This is what human-in-the-loop looks like when it's load-bearing.

---

## The kingdom is just one domain

Swap the rule book, swap the minister documents, swap the checklist. The pipeline runs identically.

The same architecture can audit:

- **University policy compliance** — student handbooks vs. accreditation requirements
- **GDPR** — internal data processing records vs. regulation articles
- **CCPA** — privacy policies vs. California consumer rights obligations
- **DPDP Act** — data handling practices vs. India's Digital Personal Data Protection Act
- **ISO 27001** — security controls vs. certification requirements
- **FDA drug labelling** — product documentation vs. regulatory standards

The retrieval doesn't know it's reading a medieval tax decree instead of a GDPR recital. The conflict detector doesn't know the difference between a minister proposing 30% army budget and a privacy policy omitting a data subject right. Domain agnosticism isn't a design goal here — it's a side effect of building it correctly.

---

## Stack

FastAPI · LangGraph · PostgreSQL · FAISS · BM25 · Reciprocal Rank Fusion · Gemini 2.5 Flash · SuperDocs API · Docker Compose · Vanilla JS

---

## Setup

For full installation, environment configuration, and a step-by-step demo walkthrough, visit the private repository.

To get the pipeline running locally you need Docker, a Gemini API key (free tier via [Google AI Studio](https://aistudio.google.com)), and a SuperDocs account. Clone, add your keys to `.env`, and run:

```bash
docker-compose up --build
```

The frontend is served at `http://localhost:8000`. Full setup guide and environment variable reference in the private repo.

---

*Built as part of the SuperDocs hiring round. Evaluated by `o-kadam`.*
