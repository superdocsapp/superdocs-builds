# Living Changelog Maintainer


A production-grade, pure-Python CLI and engine for maintaining a **single, living changelog document** release after release. 

Built specifically for open-source maintainers and DevRel teams who want immutable release history, strict house style consistency, zero-spend previewing, and automated exports to **Markdown**, **Word (`.docx`)**, and **PDF** via [SuperDocs](https://api.superdocs.app).

---

## ⚡ Core Guarantees & Architectural Highlights

1. **Byte-Identical Historical Invariance ($1 \dots N-1$)**:
   - Updating for release $N$ guarantees that releases $1 \dots N-1$ remain **100% byte-identical**.
   - Every historical release is verified using SHA-256 canonical hashing and live DOM/HTML anchor analysis. Prior release notes never get modified, reformatted, or drifted.

2. **AI Surgical Section Inserts**:
   - Powered by SuperDocs AI, new releases are inserted surgically at the top anchor heading without rewriting or touching surrounding document chunks.

3. **Zero-Spend Preview & Safety**:
   - `preview` and `update --dry-run` perform local rendering and canonical hash verification with **zero API calls and zero quota consumption**.

4. **Strict House-Style Consistency**:
   - Standardized Keep-a-Changelog section order: `Added` → `Changed` → `Fixed` → `Breaking` → `Deprecated` → `Removed` → `Security`.
   - Automatic comparison link formatting (e.g. `[Compare v1.4.0...v1.5.0](...)`) with duplicate link protection.
   - Clean italicized subtitle blockquotes (`> *Summary*`) and contributor credits.

5. **Zero External Runtime Dependencies**:
   - 100% Python standard library (`urllib`, `dataclasses`, `argparse`, `json`, `re`, `hashlib`). No heavy frameworks, ORMs, or database servers required.

---

## 🚀 Quickstart

### 1. Prerequisites
- Python 3.11 or higher
- SuperDocs API Key (set in `.env` or as an environment variable)

Create a `.env` file in the root directory:
```bash
SUPERDOCS_API_KEY=your_superdocs_api_key_here
```

### 2. Update the Changelog (One-Command Flow)
You can update your changelog with a single command:

```powershell
python changelog.py update release-1.6.0.json --format md,docx
```

*(If the changelog hasn't been initialized yet, it will automatically register and initialize the living document on SuperDocs for you!)*

---

## 📖 CLI Workflow & Commands

### `update` — Apply a New Release Surgically
Performs the targeted SuperDocs insert, verifies prior entries, and exports the requested formats:
```powershell
# Update and export to Markdown + Word DOCX
python changelog.py update release-1.6.0.json --format md,docx

# Safe dry-run (0 spend, verifies hashes locally)
python changelog.py update release-1.6.0.json --dry-run
```

### `preview` — Zero-Spend Local Review
Renders the candidate release entry and computes SHA-256 stability without making any network calls:
```powershell
python changelog.py preview release-1.6.0.json
```

### `init` — Initialize a New Standing Changelog
Explicitly create a new living document state:
```powershell
python changelog.py init --title "Awesome Project Changelog" --owner my-org --repo awesome-project
```
*Flags:*
- `--force`: Overwrite existing state file if starting over.
- `--local-only`: Skip SuperDocs remote creation (local state only).

### `verify` — Verify Document Integrity
Validates that every historical entry in the local state matches its canonical SHA-256 hash:
```powershell
python changelog.py verify
```

### `export` — Export Document Formats
Re-exports the current document to one or more formats:
```powershell
python changelog.py export --format md,docx,pdf
```

### `publish` — Open a GitHub Pull Request
Creates a new branch and opens a PR with the updated changelog:
```powershell
python changelog.py publish --repo my-org/awesome-project --title "Release 1.6.0" --github-token ghp_...
```

---

## 📝 Release Payload Format (`release.json`)

Payloads can be provided with simple string lists or structured link objects:

```json
{
  "version": "1.6.0",
  "date": "2026-08-28",
  "title": "Multi-language support and safer previews",
  "sections": {
    "Added": [
      "Full multi-language changelog generation",
      "No-spend preview mode that never calls SuperDocs",
      "Identity check that older releases stay byte-identical"
    ],
    "Changed": [
      "House style is now enforced on every insert",
      "Export always produces Markdown + PDF by default"
    ],
    "Fixed": [
      "Duplicate compare links no longer appear",
      "Section order is now consistent across all releases"
    ],
    "Breaking": [],
    "Removed": [
      "Old experimental --force-rebuild flag"
    ]
  },
  "contributors": ["@alice", "@bob", "@dave"],
  "links": {
    "compare": "https://github.com/org/repo/compare/v1.5.0...v1.6.0",
    "release": "https://github.com/org/repo/releases/tag/v1.6.0"
  }
}
```

---

## 📂 Output Artifacts

All exports and standing state files are written to the `output/` directory and root:
- **`output/CHANGELOG.md`**: Clean, standard-compliant Markdown changelog.
- **`output/CHANGELOG.docx`**: High-fidelity Word document for DevRel / stakeholder distribution.
- **`changelog.state.json`**: Source of truth tracking the SuperDocs document ID and historical release hashes.

---




---

