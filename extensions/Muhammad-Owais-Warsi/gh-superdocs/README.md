# gh-superdocs

> Built by **Muhammad Owais Warsi** for the [SuperDocs engineering task](https://docs.superdocs.app).

GitHub CLI extension for the SuperDocs document-editing API. Upload documents, send edit instructions, approve/reject proposed changes, and export finished files — all from the terminal.

**Standalone repo:** [github.com/Muhammad-Owais-Warsi/gh-superdocs](https://github.com/Muhammad-Owais-Warsi/gh-superdocs)

## Screenshot

<!-- TODO: Replace this with an actual screenshot before merging -->
![gh-superdocs demo](TODO-add-screenshot.png)

## What it does

| Command | What it does |
|---------|-------------|
| `gh superdocs upload <file>` | Upload a local file to SuperDocs, get a Doc ID |
| `gh superdocs edit <doc-id> "<instruction>"` | Send a natural-language edit instruction |
| `gh superdocs approve <doc-id> <change-id> [--reject]` | Approve or reject a proposed change |
| `gh superdocs export <doc-id> <output-path>` | Export the finished document to a file |

## Install

```sh
gh extension install Muhammad-Owais-Warsi/gh-superdocs
export SUPERDOCS_API_KEY="your-key-here"
```

## SuperDocs features used

- **Upload API** — document ingestion
- **Chat API** — targeted edit instructions with proposed changes
- **Approve API** — item-by-item change approval/rejection
- **Export API** — finished document export to markdown/docx/pdf
