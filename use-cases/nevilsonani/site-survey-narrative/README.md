# Site Survey → Design Narrative

**Built ON SuperDocs** for the SuperDocs builder round, by **Nevil Sonani**.

A solar site survey comes back as a pile of photographs, a measurements sheet
and a few voice notes. This app turns that pile into an engineering document a
designer who never visited the site can actually use — with every observation
tied to the exact photograph (or measurement row, or voice note) that proves
it, and everything the evidence *cannot* prove parked under **"Requires Second
Visit"** instead of invented.

## What it does

1. **Uploads the survey bundle** — every photo goes to the SuperDocs session as
   a reference attachment (`POST /v1/attachments/upload`), and the app waits
   for processing (`GET /v1/attachments/status/{session}`) — a long silence is
   "still processing", not a crash.
2. **Drafts the assessment** with one async chat call in **review mode**
   (`POST /v1/chat/async`, `approval_mode: "ask_every_time"`): roof structure &
   condition, shading with obstructions named, electrical service, access &
   safety, and the resulting design assumptions & constraints. The instruction
   hard-requires an evidence tag on every observation and forbids claims the
   evidence cannot back.
3. **Human gate** — proposed changes come back as pending changes on the job;
   the CLI shows each one and you approve/reject **item by item** (or pass
   `--auto-approve` when a machine drives the flow). Decisions go through
   `POST /v1/chat/{session}/approve`.
4. **Exports** DOCX + Markdown (`POST /v1/documents/export` — exports cost no
   operations, so it saves early and often).
5. **Verifies its own grounding** — the app re-parses the exported narrative:
   every observation line in an evidence-bearing section must cite an evidence
   id that exists in the bundle; a citation to a file that does not exist
   fails the run. Unsupported claims are only legal inside "Requires Second
   Visit". This is the app refusing to bluff, checked after the fact.

## Quickstart

```bash
cd nevil-sonani-site-survey
cp .env.example .env          # put your sk_ key in (or agent-signup: see docs)
uv run python scripts/gen_bundle.py   # regenerate the synthetic bundle (committed)
uv run s2n run --auto-approve         # full machine-driven run
uv run s2n run                        # same, but you gate each change yourself
uv run s2n verify-doc out/site-assessment-XXXXXX.md   # re-check grounding
```

Budgeting: `--max-photos 3` is the small-sample mode for a cheap first run;
`S2N_OP_BUDGET` (default 25) is a hard stop — the app refuses to start an
operation that would exceed it, and prints ops used after every run.

## The bundle (fictional, on purpose)

`bundle/` is a synthetic survey of a fictional residence ("Malhotra
Residence, Ahmedabad") — the task explicitly asks for invented clients and
fabricated data. The 12 "photographs" are generated, annotated stand-ins:
each PNG depicts what the camera saw with the observation burned into the
image itself, so the document AI reads evidence **from the attachment**, not
from captions smuggled into a prompt. A real deployment uploads the
surveyor's actual JPEGs through exactly the same code path.

Seeded honesty checks: the voice notes contain things no photo supports (an
unverified RCD, a rusted-shut earth pit, a planned extension) — a correct
narrative must route them to "Requires Second Visit" / constraints with
voice-note citations, not state them as site facts.

## Surfaces used

attachments (images) · async chat with HITL review · approve · export ·
sessions. (Card surfaces "search" and "templates" are natural extensions:
save the narrative as a template per client, search prior surveys — not built
in v1, and nothing here depends on them.)

## Bugs found while building (reported)

- The docs' "upload reference file (pdf/docx/**image**)" page notwithstanding,
  both attachment endpoints 415 on raw `.png` — hence the photo-log PDF
  (which SuperDocs' vision then reads genuinely well, image-only pages
  included).
- `GET /v1/attachments/status/{session}` stays empty for base64 uploads; the
  upload's returned `job_id` polled via `/v1/jobs/{id}` is the working path.
- Parallel placeholder edits can duplicate section headings / append a second
  report fragment unless the instruction says "edit IN PLACE, never insert or
  repeat headings".
- Markdown export escapes underscores (`IMG\_03...`), which breaks naive
  citation parsers — the grounding verifier normalizes for it.

## Honest limitations

- The narrative's factual quality is bounded by what SuperDocs' attachment
  understanding extracts from the images; the grounding verifier catches
  missing/fabricated *citations*, not wrong *readings* of a photo. The human
  gate is where a wrong reading dies.
- Voice notes are pre-transcribed text in v1 (real audio → Whisper is a
  one-function addition).
- One draft call per run keeps cost ~2-3 operations; iterative section-by-
  section refinement is a `--sections` flag away but costs more.

*Built for the SuperDocs task; screenshot in `docs/` after the first run.*
