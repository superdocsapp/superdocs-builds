# Rights/Talent Agreement Generator

A template-driven media agreement workflow built on SuperDocs. Fictional deal terms are validated with Pydantic and checked after generation for term, rights/media, territory, compensation, deliverables, approvals, credit, and termination coverage.

> Built by Anurag Mishra for the SuperDocs Round 2 engineering task.

## Offline deterministic proof

```powershell
python -m pip install -e ".[dev]"
python scripts/run_tests.py
python -m rights_talent_generator.cli --terms fixtures/maya-chen-deal.json --template fixtures/template.md --out generated-agreement.md
```

Offline mode replaces explicit template tokens and runs the same clause checks without a key or billable operation.

## Live SuperDocs workflow

Install the sibling SDK and set `SUPERDOCS_API_KEY` server-side:

```powershell
python -m rights_talent_generator.cli `
  --terms fixtures/maya-chen-deal.json `
  --template fixtures/template.md `
  --out generated-agreement.md `
  --docx-out generated-agreement.docx `
  --live-superdocs
```

The live path:

1. uploads the actual template into a unique session;
2. starts a durable async chat with `approval_mode="ask_every_time"`;
3. shows every `metadata.pending_changes` item and requests a human decision;
4. submits typed per-change approvals;
5. resumes the same job to completion;
6. retrieves final HTML, exports DOCX, converts a clean Markdown companion, and rejects incomplete clause coverage.

For a controlled non-interactive demonstration, `--approve-all` is an explicit opt-in. It is never the default.

The tests use a contract fake to prove upload → chat → item gate → export ordering, approval payloads, DOCX bytes, template-path use, clause completeness, and safe HTML-to-Markdown conversion.
