# eCTD Module 2 Summary Assembler

Built for the SuperDocs engineering task.

Automates drafting of eCTD Module 2 clinical summaries from Module 5 study reports. A regulatory ops engineer runs one command; the regulatory writer reviews citations and proposed edits in SuperDocs; the script exports a submission-shaped `.docx`.

## Who it serves

- **Regulatory writer** — reviews drafted sections, citations, and proposed changes in the SuperDocs web UI
- **Regulatory ops / automation engineer** — runs the assembler, maintains `manifest.json`, and manages reruns when study reports change

## SuperDocs features used

- REST API: document upload, attachment upload, async chat, approve, export
- Multi-document sessions (Module 2 shell + Module 5 attachments)
- Human-in-the-loop review (`ask_every_time` approval mode)

## Setup

```bash
git clone https://github.com/superdocsapp/superdocs-builds.git
cd superdocs-builds/use-cases/Umesh-Bhati/ectd-assembler
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python generate_test_data.py
export SUPERDOCS_API_KEY="your-key-here"
```

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

For human review in the browser instead of programmatic approve:

```bash
python main.py --browser-review
```

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

Expected: all three sections (`2.5.1`, `2.5.2`, `2.5.3`) are drafted and exported.

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

## Tests (no live API key required)

```bash
python -m unittest discover -v
```

## Known limitations

- **Browser sync:** When using `--browser-review`, the web editor may not auto-refresh after API edits — reload the session tab if content looks stale
- Synthetic Module 5 sources are plain `.txt` files, not full study-report PDFs/DOCX
- Citation quality depends on SuperDocs AI following prompt instructions; citations are not independently validated
- Section diff proof compares extracted paragraph text, not byte-identical DOCX structure
- Large documents may pause for SuperDocs "continue" prompts during drafting

## Demo video

[Watch the pipeline in action here (placeholder)](#)
