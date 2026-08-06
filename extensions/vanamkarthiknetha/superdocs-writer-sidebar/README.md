# SuperDocs Writer Sidebar

A native LibreOffice Writer extension: a sidebar panel for sending the current
selection (or the whole document) to SuperDocs with a natural-language editing
instruction, reviewing the proposed changes, and applying approved ones back
into the document **range by range** — untouched text is never rewritten, and
existing paragraph/character styles are respected.

> **Status: v0.2 — selection round-trip working, validated on Linux and
> Windows.** Select a passage, describe the edit, review the actual proposed
> text, Apply → only the selected range changes, with its styles intact
> (verified on heading and character styles). Current limits, stated honestly:
> selection-based edits only (whole-document mode and drafting-at-cursor are
> the v0.3 milestone), and write-back is plain text into the styled range —
> formatting *inside* a proposal isn't carried yet.

## Screenshots (Linux, WSLg)

| Sending a selection | Applied in place |
|---|---|
| ![Sending](screenshots/linux-sending.png) | ![Applied](screenshots/linux-applied.png) |

A `Heading 1` paragraph edited via the sidebar: the text changed, the heading
style survived untouched.

## Build

```bash
python build.py        # -> dist/superdocs-writer-sidebar.oxt
```

Stdlib-only build; the source layout under `src/` is the .oxt layout.

## Install (Linux)

```bash
sudo apt install libreoffice-writer python3-uno   # python3-uno = Python component loader
unopkg add -f dist/superdocs-writer-sidebar.oxt
```

Then open Writer → **View → Sidebar** → the **SuperDocs** deck appears in the
tab rail. (Windows note for development: use `unopkg.com`, not `unopkg.exe` —
the latter detaches from the console and can fail silently.)

## How it talks to SuperDocs

- The selection goes up as passage text (`/v1/documents/upload-base64` into a
  fresh session) — SuperDocs takes documents, never raw XML.
- `POST /v1/chat/async` with `approval_mode: "ask_every_time"`; the panel polls
  the job and previews the **actual proposed content** (`new_html`, tag-stripped)
  rather than the AI's self-description, which can paraphrase.
- Approvals always send the explicit `changes` array — a bare
  `{job_id, approved:true}` is a silent no-op in the API (discovered and
  reported during this project).
- The approved result (plain-text export of the session) is written back through
  the stored UNO text range with `setString`, inheriting the range's current
  styles — no hard formatting, no whole-file replacement, untouched text is
  never rewritten.
- All network work runs on a background thread; UI and document updates are
  marshaled to the office main thread via `AsyncCallback`.
- API key: `SUPERDOCS_API_KEY` environment variable, else
  `~/.superdocs/agent_credentials.json`. Never hardcoded, never in this repo.

## Tests

`tests/run_style_test.sh` (Linux) starts a throwaway headless LibreOffice on an
isolated profile, builds a document with a Heading 1, a bullet list, and a
table, edits one body paragraph through the exact client + write-back path the
panel uses, and asserts the heading/list/table styles and content all survived.
Costs 1 operation. Passing run ends with `STYLE TEST: ALL PASS`.

(Portability note discovered by this test: LibreOffice 26 dropped the classic
"List Bullet" paragraph-style family — bullets are now "List 1".."List 5" — so
the test discovers style names at runtime instead of assuming them.)

## Files

| Path | Role |
|------|------|
| `src/description.xml` | Extension identity/version |
| `src/META-INF/manifest.xml` | Declares the two .xcu configs + Python component |
| `src/config/Sidebar.xcu` | Registers the SuperDocs deck + panel in Writer's sidebar |
| `src/config/Factories.xcu` | Maps the panel's resource URL to the Python factory |
| `src/panel.py` | UNO component: panel factory, panel, threading, write-back |
| `src/panel.xdl` | Panel UI (instruction box, Send, preview, Apply/Reject, status) |
| `src/pythonpath/superdocs_client.py` | Stdlib SuperDocs client (upload → async chat → approve → export) |
| `src/icons/superdocs_24.png` | Sidebar deck icon |

Built by Karthik Vanam for the SuperDocs hiring round, with AI-assisted
development (Claude Code).
