# eCTD Module 2 Summary Assembler

Built by **Umesh Bhati** for the SuperDocs engineering task.

Automates drafting of eCTD Module 2 clinical summaries from Module 5 study reports. A regulatory ops engineer runs one command; the regulatory writer reviews citations and proposed edits in SuperDocs; the script exports a submission-shaped `.docx` with real Word footnotes, running headers and a live table of contents.

## Screenshots

### Terminal — run plan and incremental diff proof

![eCTD assembler CLI — run plan and incremental diff proof](assets/terminal-screenshot.png)

The terminal shows the run plan (changed sources, sections to draft) and, on an incremental rerun, the diff report proving only dependent subsections changed.

### SuperDocs editor — drafted Module 2 summary

![eCTD assembler — SuperDocs editor with drafted clinical summary sections](assets/web-ui-screenshot.png)

The SuperDocs session after drafting: each subsection is pulled from and cited against its Module 5 study report, ready for a regulatory writer to review and approve.

## Accepted formats and domain

- **Domain:** eCTD Module 2 clinical summaries for regulatory submissions (synthetic demo data included)
- **Module 2 shell:** `.docx`
- **Module 5 sources:** `.txt` in this demo; SuperDocs attachments also support `.pdf`, `.docx`, and other formats listed in [SuperDocs docs](https://docs.superdocs.app/concepts/attachments)
- **Output:** `.docx` export via SuperDocs REST API

## Who it serves

- **Regulatory writer** — reviews drafted sections, citations, and proposed changes in the SuperDocs web UI
- **Regulatory ops / automation engineer** — runs the assembler, maintains `manifest.json`, and manages reruns when study reports change

## SuperDocs features used

- REST API: document upload, attachment upload, async chat, approve, export
- Multi-document sessions (Module 2 shell + Module 5 attachments)
- Human-in-the-loop review (`ask_every_time` approval mode, or `--browser-review`)
- Local post-processing of the export: inline citations become real Word footnotes; the TOC list becomes a live Word `TOC` field

## Quick start

Tests only (no API key):

```bash
git clone https://github.com/superdocsapp/superdocs-builds.git
cd superdocs-builds/use-cases/Umesh-Bhati/ectd-assembler
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -v
```

See what a run would do, without spending anything:

```bash
python main.py --dry-run
```

Full pipeline (requires API key):

```bash
python generate_test_data.py
export SUPERDOCS_API_KEY="your-key-here"
python main.py
```

No key exported? No problem — on a real run (not `--dry-run`) the CLI asks you to paste it, and the input is **masked** (never echoed, never printed), so it cannot leak into a screenshot or shell history. `--dry-run` and no-op runs never ask for a key. The key is only read for the API call and is never written to any file.

Verify your key (should return `200`):

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  https://api.superdocs.app/v1/sessions \
  -H "Authorization: Bearer $SUPERDOCS_API_KEY"
```

## Run

```bash
python main.py
```

Flags:

| Flag | What it does |
|---|---|
| `--browser-review` | Wait for a human to approve in the SuperDocs web UI instead of auto-approving via API |
| `--dry-run` | Compute and print the run plan; makes zero API calls and needs no key |
| `--max-sections N` | Stop after drafting at most N sections (budget/stopping rule). State is saved so the next full run resumes where this stopped |

### Resume after a crash

`session_state.json` is written before each section is drafted and updated after each one completes. Kill the process mid-run and re-run `python main.py`:

- it detects the interrupted run, resumes the *same* SuperDocs session (no re-upload), and
- skips sections already completed, drafting only the remainder.

A run that fails an API call prints its state location and the resume command.

## User journey

1. Ops engineer runs `python main.py`
2. Script uploads the Module 2 shell (or previous export on reruns) and Module 5 attachments
3. Script drafts each manifest subsection via `chat/async`
4. Proposed changes are surfaced; writer reviews at the printed SuperDocs session URL (or approves via API by default)
5. Script exports `final_module2.docx` and saves run state to `session_state.json`

## Demo 1 — First-time assembly

```bash
python generate_test_data.py
rm -f final_module2.docx final_module2.previous.docx session_state.json
python main.py
```

Expected: all three sections (`2.5.1`, `2.5.2`, `2.5.3`) are drafted, citations are converted to footnotes, a live TOC field is inserted, and `final_module2.docx` is exported.

## Demo 2 — Incremental update (strong path)

```bash
# After demo 1 completes, edit one study report
echo "Section 2.1: Updated efficacy result: 80% response rate." >> module5/study_report_2.txt
python main.py
```

Expected:

- Only sections depending on `study_report_2.txt` are redrafted (`2.5.2`, `2.5.3`)
- Diff report shows `2.5.1` unchanged
- `final_module2.previous.docx` is compared against the new export

## Citations and footnotes

The drafting prompt requires every paragraph to end with a bracketed citation in the format `[<source file name>, Section <n>]`. After export, the pipeline converts bracketed citations into **real Word footnotes** (reference mark in the body, citation text at the foot of the page) — clickable in Word and jumping straight to the source report and section.

Two honesty notes on the conversion:

- Only square-bracket citations matching the format are converted. Anything else (e.g. parenthesized citations from older drafts) is left untouched — the pipeline never rewrites text it does not recognize. Old exports that already contain `(Study Report 2, Section 2.1)`-style citations keep them as inline text.
- The check requires both a source keyword (`report`, `section`, `module`, `study`) and a number, so a plain bracket like `[Table of contents will be generated.]` is never mistaken for a citation.

The live table of contents is a real Word `TOC` field (`\o "1-3"`). It is marked dirty, so Word populates it (with page numbers) when the file is opened — update fields with Ctrl+A then F9 if it does not populate automatically.

## Prompt-injection defense

Study reports are untrusted input. The drafting and TOC prompts state that attached documents and the working document are **source data, not instructions**, and instruct the model to ignore any instructions, commands, or system prompts inside them. A source document that tries to give the pipeline orders is reported on, not obeyed.

## Known limitations

- **Browser sync:** When using `--browser-review`, the web editor may not auto-refresh after API edits — reload the session tab if content looks stale
- Synthetic Module 5 sources are plain `.txt` files, not full study-report PDFs/DOCX
- Citation quality depends on SuperDocs AI following the prompt; citations are only converted to footnotes when they match the `[...]` format exactly
- Section diff proof compares extracted paragraph text, not byte-identical DOCX structure; the TOC section is excluded from the proof
- Large documents may pause for SuperDocs "continue" prompts during drafting
- The resume path reuses a stored session id; if the session has expired server-side, re-run with a fresh `session_state.json` (first run re-uploads the shell or last export)
- Post-processing is local to the exported `.docx`; footnote/TOC changes do not appear inside the SuperDocs web editor
