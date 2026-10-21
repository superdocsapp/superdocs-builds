# Multi-Agent Editorial Review Loop

Built by Shivansh Kalra for the SuperDocs task.

A writer agent expands a bullet-point outline into a full first draft; a
fact-checker agent and a style-reviewer agent then work the same
document, on two genuinely disjoint sets of sections, fired as real
concurrent API calls rather than sequential turns, in a loop that's
bounded by construction rather than hoped to stop.

All content is synthetic: a fictional smart-home hub (Aurora Home Hub)
and a fictional internal fact sheet and style checklist.

Two things this build is specifically built to prove, not just assert --
see [Verified result](#verified-result) for what actually held up:

1. **No section collisions.** The fact-checker's target sections (Market
   Analysis, Risk Assessment) and the style-reviewer's target sections
   (Executive Summary, Technical Specifications) are disjoint by
   construction, and both turns' submissions are fired at the same
   instant against the same session.
2. **Provable loop termination.** The review loop is a plain `for` loop
   over `range(1, MAX_ROUNDS + 1)` with an early `break` on convergence --
   it terminates in at most `MAX_ROUNDS` iterations by construction,
   whether or not the agents ever agree the document is clean.

## What it does

1. Uploads the bullet-point outline (focused) plus two reference
   documents as background: `verified_facts` (the two real figures) and
   `style_guardrails` (four editorial rules, two of which the draft
   already satisfies).
2. **Writer turn**: expands each section's bullets into full prose,
   keeping every fact and number exactly as stated.
3. **Review rounds** (up to `MAX_ROUNDS = 2`): each round fires the
   fact-checker and style-reviewer's *submissions* at the same instant
   via a `ThreadPoolExecutor`, checks all four planted issues against the
   resulting document, and stops early if everything's resolved.
4. Exports the result and verifies it programmatically by inspecting the
   real returned HTML, not by asserting success.

`verify_issues()` was validated in both directions before any real API
call: a hand-built bloated pre-review draft (all four checks correctly
fail) and a hand-built fully-fixed version (all five correctly pass).

## How to run it

```bash
python -m venv .venv
.venv/Scripts/activate    # or source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env      # then set SUPERDOCS_API_KEY
python build.py --dry-run # prints the full plan, zero API calls
python build.py           # runs it for real
```

## SuperDocs features used

- **Multi-document sessions** (`open_mode: "replace"` / `"background"`) --
  the draft plus two reference documents open together
- **Chat / async edit** (`POST /v1/chat/async`) with
  `approval_mode: "ask_every_time"`, fired concurrently against one
  session via a `ThreadPoolExecutor`
- **Export** (`POST /v1/documents/export`, `.docx`)

## Verified result

Two real runs against the live API (a third was a script crash from
chasing a false failure -- full trace in
[`PROGRESS.md`](PROGRESS.md)). Final, clean run:

| Check | Result |
|---|---|
| TAM figure corrected ($2.8B, not $4.2B) | PASS |
| Competitor market share corrected (38%, not 61%) | PASS |
| Executive Summary <= 80 words | PASS |
| No passive voice in Technical Specifications | PASS |
| Risk Assessment mitigations untouched | **FAIL** |

Overall: **FAIL, 4 of 5.** Both fact corrections landed, both style
fixes landed, and both guardrails that were already satisfied stayed
untouched everywhere except one place: the fact-checker, while correcting
the one figure it was scoped to touch, reworded the *other* risk's
mitigation sentence too -- from `"Mitigation: qualify a second supplier"`
to `"To address this vulnerability, we intend to qualify a second
supplier"` -- despite an explicit instruction not to change anything else
in that section. The mitigating action is still there in substance; the
literal word a downstream guardrail's language depends on isn't. That's
a real scope-discipline finding about the fact-checker turn, not a
verification-script bug -- see PROGRESS.md for how that was told apart
from two verification bugs that *did* turn up along the way and got
fixed instead of reported as findings.

**Both things this build set out to prove came back true, for different
reasons than expected:**

- **No section collisions**: true, but because `POST /v1/chat/async`
  returns `409 Conflict` outright when a second chat request lands on a
  session that already has one active -- collisions are structurally
  prevented by the platform, not just empirically absent. `run_turn`
  retries on 409 with backoff, which is what two agents genuinely racing
  to edit one document have to do against this API.
- **Provable loop termination**: true, and directly demonstrated -- the
  loop ran its full 2 rounds and stopped on the hard cap without
  converging, exactly as the bounded `for` loop guarantees regardless of
  outcome.

## Honest limitations

- The fact-checker turn's scope discipline isn't perfect: it corrected
  the right figure but also touched wording elsewhere in its assigned
  section that it was told to leave alone. Not investigated further as
  its own bug report -- noted here as what it is.
- `output/` is gitignored; run `python build.py` to regenerate
  `reviewed_launch_brief.docx`, `final_document.html`,
  `verification_result.json`, and `round_log.json`.

## Files

- `build.py` -- upload -> writer -> review rounds (concurrent
  fact-check + style-review, verify, retry up to `MAX_ROUNDS`) -> verify
  -> export flow, plus `--dry-run`
- `content/brief_outline.html` -- the launch brief outline, authored with
  two planted factual errors and two planted style violations
- `content/verified_facts.html`, `content/style_guardrails.html` -- the
  fact-checker's and style-reviewer's reference documents
- `PROGRESS.md` -- full diagnostic trace across three runs, including how
  two real verification-script bugs were told apart from the one real
  platform/scope finding
