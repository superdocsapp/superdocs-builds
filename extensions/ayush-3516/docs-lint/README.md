# docs-lint

A house-style gate for Markdown documents in a repository. Runs as a pre-commit hook and in CI,
checks changed documents against your team's style guide, and proposes corrections as a reviewable
change set that a human approves item by item — it never rewrites your prose behind your back.

Built on [SuperDocs](https://use.superdocs.app). Built for the SuperDocs task.

> **Status: in development.** This README is filled out as the build lands.

## What it does

- Checks only the documents you touched, so it stays fast on a large repository
- Findings map to precise locations — heading path, line range, character offsets
- Your style guide is **data, not code**: a Markdown file uploaded once as a SuperDocs reference.
  Any team swaps theirs in without touching this codebase.
- Configurable severity per rule; exits non-zero only on the severities you choose
- `--fix` proposes corrections for human approval and applies only what was approved

## Scope

Accepts `.md` and `.mdx`. DOCX is deliberately out of scope — see `PROGRESS.md` for the reasoning.

## Quickstart

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev]'
```

Full setup, configuration and usage documented as the build lands.

## SuperDocs features used

Reference-file attachments, document upload with chunk-id structural editing, async chat jobs,
the human-in-the-loop per-item approval API, and Markdown export.

## License

MIT, per this repository.
