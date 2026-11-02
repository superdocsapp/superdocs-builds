# Project instructions

The working contract for this repository. Follow it in every session that
changes code here.

This is attorney-support drafting software for immigration RFE responses.
It is not legal advice and it never decides eligibility. That framing
constrains every change: when a choice would move the tool toward deciding
for the attorney rather than supporting them, it is the wrong choice.

## Source priority

1. `NOTES.md` — assumptions, the decisions behind the design, known
   limitations, and the verification evidence. The reasoning of record.
2. `README.md` — current user-facing behaviour, commands, and the
   SuperDocs surface actually used.
3. The code and its tests.

When a document and the code disagree, the code is what ships — fix the
document in the same change, never in a later one.

## Before changing anything

- Read the relevant entry in `NOTES.md` first. A decision recorded there
  is closed; do not silently reopen or reinterpret it.
- Run the suite before you start, so a failure you see later is yours.
- Work out which door the change touches. If it touches behaviour, it
  belongs in a core function that both the CLI and the MCP server call —
  not in one door.
- If the brief, the recorded decisions, and the requested change disagree,
  stop and ask rather than picking one.

## While changing code

- **Write the test first.** A bug fix lands with the test that would have
  caught it. A behaviour change lands with the test that pins the new
  behaviour.
- **Never weaken a guard to make something pass.** The human gate, the
  export verification, and the operation budget exist because each one
  already caught a real failure. If one blocks you, the run is wrong, not
  the guard.
- **Keep `engine/` offline.** No network, no API key, no SuperDocs types.
  Anything that talks to the API goes through `superdocs/client.py` and
  nowhere else, so the budget cannot be bypassed.
- **Do not let the model do code's job.** Retrieval, the skeleton,
  citation placement, and the checklist are deterministic. The model
  judges coverage and writes prose into placeholders — nothing more.
- **Never invent evidence, and never let the tool.** Where the petition
  does not answer a request, the output says so. A gap is stated, not
  filled.
- **Fail loudly, degrade honestly.** No silent success. If a step cannot
  be completed, say which one and what the user should do next — without
  naming a command that only exists on one of the two doors.

## Spending and secrets

- Every billable call is a decision. Before adding one, ask whether the
  same result can come from code or from a cached earlier response.
- The operation cap is a development guard, not a bill. Do not raise the
  default to make a run finish.
- The API key comes from the environment only. Never commit a key, a real
  document, or anything from `output/`.

## Test data

- Every person, employer, and filing in this repository is invented for
  this project. Real client documents must never enter it.
- Blind test cases exist to be unseen. Do not tune the parser or the
  retriever against a specific blind case to make it pass — fix the
  general rule, or record the limitation in `NOTES.md`.

## Finishing

- Run the full suite. It must pass offline, with no key and no network.
- Update `README.md` only when user-facing behaviour, commands, formats,
  or limitations actually changed.
- Add a new assumption, decision, or limitation to `NOTES.md` as soon as
  it is real — not at the end of the work.
