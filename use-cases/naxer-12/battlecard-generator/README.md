# Sales Battlecard Generator

Built for SuperDocs' Task 2, assigned build 2. Feed it a fictional competitor's name plus a few
structured inputs (their likely pitch, where we win, where we don't), and it produces a
consistent, exportable one-page battlecard on a fixed template — a fast, rep-facing answer to "why
not them," not a quarterly win-loss retrospective.

## What it does

1. Builds a one-page battlecard from a fixed template: title, then four sections — **Their
   Pitch**, **Where We Win**, **Where We Don't**, **Talk Track**.
2. Fills in everything except the last section directly, with plain text substitution. No AI call
   needed for text the caller already handed over verbatim.
3. Uploads that partially-filled document to a fresh SuperDocs session and asks it to write the
   one thing that actually needs judgment: a single talk-track sentence synthesizing the win/loss
   points into something a rep could say out loud.
4. Polls the edit to completion, exports the finished `.docx`, and saves it.

## Why it's split that way (a real design change, not the original plan)

The first version asked SuperDocs to fill in all four sections in one instruction. It worked, then
on the very next run with the identical instruction it only filled in one of the four sections and
left three as literal placeholder text. Confirmed directly: two calls, same input, different
completeness. That's a real characteristic of the live model, not a bug in this code — verified by
inspecting the raw job response from both runs.

The fix wasn't a retry loop. It was noticing that three of the four sections don't need an AI at
all — "Their Pitch," "Where We Win," and "Where We Don't" are just the caller's own text, copied
into place. Only "Talk Track" requires synthesizing two things into one new sentence. So that's the
only part that goes through SuperDocs now. Fewer things asked of the model, less for it to
inconsistently skip, and it's a more honest use of what SuperDocs is actually good at.

## Running it

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

./venv/bin/python cli.py \
  --api-key sk_... \
  --competitor "Zephyr Analytics" \
  --pitch "Fastest dashboard to set up, no engineering needed." \
  --win "Our reports stay accurate automatically when the data model changes; theirs silently drift." \
  --dont-win "Their onboarding really is faster for a first, simple dashboard."
```

Or set `SUPERDOCS_API_KEY` instead of passing `--api-key`. Output lands in `output/` by default
(`--output-dir` to change it), named `battlecard-<competitor>.docx`.

## Running the tests

```bash
./venv/bin/python -m pytest -v
```

15 tests, all keyless — the HTTP layer is mocked with `responses`, but every mocked shape matches
what the real API actually returns (verified live against a real account, not guessed from docs;
see `superdocs_client.py`'s module docstring for the specific gotchas that came out of that:
`session_id` isn't auto-generated, `document_changes` is nested under `result`, `approve` needs
`job_id`, a job can auto-complete with no approval step, and `Content-Disposition` can carry two
filename forms on one line).

## Proof it satisfies the brief's own bar

> "Two different fictional competitor inputs produce battlecards that read as genuinely different
> documents rather than one paragraph with a name swapped, and every card exports cleanly from the
> same template."

Ran it twice for real against the live API, with two unrelated fictional competitors (Zephyr
Analytics, a dashboard tool; Brightfield Governance, a compliance-focused platform). Both exported
cleanly. The talk-track sentences are genuinely different, each grounded in that competitor's own
win/loss points, not a template with a name swapped in:

- *Zephyr*: "While their onboarding is faster for simple dashboards, Zephyr Analytics keeps your
  reports accurate automatically when data models change, so you never have to worry about silent
  drift before a board meeting."
- *Brightfield*: "While they may have more extensive compliance certifications, we deliver new
  integrations in days instead of quarters and guarantee same-day support responses."

## Known limitations

- The AI-generated talk track is only lightly guarded against inventing claims beyond the given
  win/loss points — the instruction asks it not to, but nothing downstream verifies that
  mechanically. For a real deployment, a grounding check similar to Task 1's (does the talk track's
  claim actually trace back to the win/don't-win input) would be the next real improvement, not a
  cosmetic one.
- Export format is whatever SuperDocs' `/v1/documents/export` supports (`docx`, `pdf`, `html`,
  `markdown`, `txt`) — no format-specific post-processing is done here.
- One competitor per run. Batch generation from a CSV of competitors would be a small, real
  addition, not built here since it wasn't asked for.

## Where this goes

Per the brief, this build's finished work belongs in a pull request to the public
`github.com/superdocsapp/superdocs-builds` repository, `use-cases/` folder — this repo
(`doctask-jainam-shah`) is Task 1's private repo. This folder is laid out to match that destination
folder name directly so moving it later is a straight copy, not a restructure.
