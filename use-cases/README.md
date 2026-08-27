# Research Paper Writing Agent

An agent that drafts a research paper end to end — outline, retrieval-grounded sections, citation verification, targeted revision — and edits the live document through SuperDocs' MCP server rather than generating a file from scratch. Built for SuperDocs' Round 2 open task list ("Research-paper writing agent, outline to submission-ready manuscript").

## What it does

Given a topic (inferred from your uploaded sources) and a set of source documents, the agent:

1. Creates a fixed 8-section outline (Abstract, Introduction, Related Work, Method, Results, Discussion, Conclusion, References) and loads it as a live SuperDocs document.
2. Drafts each section using retrieval-augmented generation — every claim is written together with the specific source passage that supports it, not generated freely and cited afterward.
3. Runs an independent supervisor pass that re-checks every claim against its cited source and flags anything unsupported.
4. Revises only the flagged claims — proven to leave every other section byte-identical, not regenerated.
5. Exports the finished, verified document as HTML or PDF.

A Streamlit UI wraps the whole pipeline: upload sources, watch section-by-section progress, edit the full draft in one place, inspect run logs and cost, check evaluation metrics, and export.

## What SuperDocs features it uses

| Feature | How it's used |
|---|---|
| **MCP** (`chat`) | Creating the live document and pushing every section's drafted/revised content |
| **MCP** (`approve_change`, `get_job`) | Auto-approving and polling SuperDocs' human-in-the-loop review gate for AI-proposed edits |
| **MCP** (`request_download_url`) | Exporting the final document as HTML or PDF |

All document editing goes through MCP — nothing in this project reads or writes a document file directly. The RAG retrieval, drafting, and verification intelligence is entirely custom, built on top of OpenAI's API; SuperDocs is the document-editing and formatting engine.

## How to run it

### 1. Environment setup (uv)

```powershell
cd research-paper-agent
uv venv
.venv\Scripts\activate
uv pip install -r requirements.txt
```

### 2. Environment variables

Create a `.env` file (never committed — see `.gitignore`) based on `.env.example`:

```
OPENAI_API_KEY=your-key-here
SUPERDOCS_API_KEY=your-key-here
SUPERDOCS_MCP_URL=https://api.superdocs.app/mcp/
```

### 3. Run the tests

```powershell
pytest tests\ -v
```

All pipeline logic is tested against fakes (no API cost). A separate, explicitly-marked suite exercises the real OpenAI API:

```powershell
pytest tests\test_openai_client.py -v -m real_api
```

### 4. Run the app

```powershell
streamlit run app\streamlit_app.py
```

Upload a few source files (`.txt`, `.pdf`, or `.docx`), click **Generate Paper**, and watch the section checklist fill in.

### 5. Run the pipeline from the command line instead (no UI)

```powershell
python scripts\run_pipeline.py --topic "Your topic" --sources-dir path\to\txt\sources
```

## Project structure

```
research-paper-agent/
├── src/                  # core pipeline: models, retrieval, drafting, verification, revision, MCP client
├── app/                  # Streamlit UI + service layer wrapping src/
├── scripts/              # CLI pipeline runner + MCP diagnostic scripts
├── tests/                # pytest suite (fakes by default, real_api marker for real OpenAI calls)
├── BUGS.md               # issues hit during development and how they were resolved
├── PROGRESS.md           # phase-by-phase build status
└── requirements.txt
```

## Known limitations

See `BUGS.md` for the full list of issues hit and fixed during development. Notably:
- Word (.docx) export was removed after a local Windows file-locking issue — HTML and PDF export both work.
- The combined draft editor splits sections on `# Heading` markers; a manually-typed line starting with `# ` inside body text would be misread as a new section boundary.

## Screenshots
<img width="500" alt="image" src="https://github.com/user-attachments/assets/447405a4-c66a-4697-be6e-470d6e3fb205" src="URL_1" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/ee480184-a28b-4beb-9fb7-8d6734ccd877" src="URL_2" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/b2ad3f3c-1e37-45b4-9de6-495403a71684" src="URL_3" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/5b3e0654-0d96-4fc1-8e8d-594d4024d288" src="URL_4" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/8692a3b2-a03b-4852-8733-37f5bd4d6b9b" src="URL_5" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/2e1ffb84-fafd-4cf4-b7d4-cb87877e62ed" src="URL_6" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/b692df39-a831-4847-a5c5-6518d4663b7e" src="URL_7" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/86f8987c-27d4-47f1-9203-fb5a50d96f14" src="URL_8" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/48a29cd6-fe2d-4ec7-9686-6943652fc8f8" src="URL_9" />
<img width="500" alt="image" src="https://github.com/user-attachments/assets/e89238ee-1a57-4f86-a922-05d9ae6cd79c" src="URL_10" />


---

Built for the SuperDocs task by Aditya Singh.
