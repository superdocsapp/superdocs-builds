# NOTES — assumptions, decisions, and evidence

A running log kept while building, as the task brief recommends. The
README says what the tool does; this file says why it is the way it is.

## Assumptions

- Notices arrive as text-bearing documents (.md, .txt, .pdf with a text
  layer, .docx). Scanned/image-only PDFs are out of scope — refused with a
  message naming OCR as the gap, never half-read.
- A list-style notice states each numbered request in one paragraph;
  heading-style notices may run several paragraphs per request. Six real layout
  styles are supported (see Verification below); an unrecognized layout is
  refused with the file's name and the layouts that would work, never
  guessed at.
- The draft's SuperDocs session id is saved in `output/run_state.json`;
  re-running resumes the same job rather than paying again. Coverage
  judging uses its own short session.
- The free tier's operations are protected by a hard cap
  (`MAX_OPS_PER_RUN`, default 10) counted from the server's own usage
  fields when present, and floored at 1 for a call we know bills when the
  server sends no number. It is a floor for the cap, not a bill. The count
  belongs to the run — draft through every decide round to export — and
  travels in `run_state.json`, so no command starts it over at zero.

## Key decisions and why

- **Code locates, AI judges, code verifies.** Word-overlap retrieval only
  *finds* material; it cannot tell whether material is *sufficient* (a
  contract ending 2027 matches every keyword of a request demanding
  coverage to 2029). So the model judges coverage per request — and code
  verifies the judgement (a claim of "answered" with no located material
  is overridden to not_provided).
- **The skeleton is code-built.** Structure, officer quotes, citations,
  the coverage checklist, and the exhibit list are deterministic; the
  model only ever fills per-request placeholder paragraphs
  (`[DRAFT RESPONSE FOR RN — TO BE WRITTEN]`). Citations start out
  code-placed from real excerpts — but an edit round can still alter or
  remove one, so the export is verified against the petition (verbatim
  quotes, real filenames, and every cited petition section still cited in
  the request it belongs to) before anything is called filed-ready.
- **Tri-state coverage** (Answered / Partially / Not provided) with a
  conservative bias: when uncertain, the system flags rather than
  reassures. A false "answered" gives an attorney false comfort before a
  legal deadline; a false "partial" costs one extra glance.
- **One core, two doors.** The CLI (rfe.py) and the MCP server
  (mcp_server.py) call the same core functions. The human gate survives
  both doors: drafting stops at proposed changes, and a decision must be
  explicit — approve_all or a per-change list — never implied.
- **Verification compares words, not markdown.** SuperDocs re-serialises
  markdown on export — found live on a blind H-1B case whose petition
  carried letterhead blocks in code fences: a correct export failed 13
  citation checks on formatting alone. What the export rewrites has
  itself changed once already (code fences stopped being rewritten in
  SuperDocs' 2026-08 update, and a `<br>` in a table cell, once a space,
  now disappears), so the comparison strips backticks, markdown backslash
  escapes and line-break tags from both sides and accepts a `<br>` read
  either as a space or as deleted; every word, number and punctuation
  mark must still match, and a changed digit is still caught.
- **A job decided elsewhere is still exported and verified.** The same
  job can be approved in the SuperDocs app, and SuperDocs expires
  undecided changes on its own; in both cases the job is `completed`
  before `decide` runs, and sending it a decision answered 400 and
  stopped the run short of the export (found on a fresh-clone walkthrough,
  2026-08-23). `decide` now reads the job first: still waiting → the
  decision is sent; already ended → the decision is skipped with a note
  carrying the server's own closing line, and the export and verification
  run as always. An expired job therefore ends as "placeholder survived —
  do not file", not as an error with the run state left behind.
- **The verdict lives next to the export.** `output/verification.md`
  records filed-ready yes/no, the checks that passed or every failure by
  name, the session and job — written by the same code path on both
  doors. The terminal line and the MCP result say the same thing, but
  neither survives a closed window; the attorney opening the folder
  later must not have to guess.
- **Graceful degradation.** A judge failure downgrades the run to the
  locator's conservative buckets; slow attachment processing does not
  block the draft; export verification failing marks the output
  "do not file" instead of pretending success.

## Known limitations

- No OCR: scanned/image-only PDFs are refused, not read.
- Legacy .doc (pre-2007 Word) is not supported; .docx is.
- The last request ends at the first all-caps line (heading styles) or the
  first blank paragraph (list styles), so trailing text of the last request
  can be cut — check the last request's officer quote in the checklist.
- Very terse notices (a request stated in a handful of words) bias the
  locator toward "partial" — deliberate, conservative direction.
- The coverage judge sees excerpts capped to fit the chat message limit
  (100k chars, discovered live on an 8-request case); on very large cases
  the judge reads less context per request.
- The lexical locator's buckets (offline preview) over-score notices that
  quote the petition back ("Evidence submitted: ..."); the judge exists
  precisely because of this, so the preview is labeled locator-only.
- The operation cap counts only what this tool can see: the server's
  own figure when one is sent, otherwise a floor of one per call known to
  bill. The true running total lives server-side.
- The cap's floor can under-count. SuperDocs' docs state one async request
  bills 1 operation per 25 sections edited, so a large document can cost
  more than the 1 the floor adds; and the approve/decide endpoint is not
  flagged billable, so a feedback round that redrafts bills invisibly to
  us. Neither is guessed at — the Billing tab and the server's own
  remaining count (surfaced in the run notes when it is sent; a
  promotional grant's balance when one is active, else the monthly plan's)
  are the truth.

## Verification evidence (all reproducible)

- **138 automated tests, no API key needed** (`python -m pytest tests/`).
- **Blind testing:** 9 fictional cases written by independent agents that
  were given no knowledge of the parser or scoring — 7 case types (H-1B,
  O-1A, L-1A, I-130 spousal, EB-2 NIW, O-1B arts, E-2 investor, H-1B
  change-of-employer, R-1 religious worker), 7 notice layout styles, 3
  formats (.md/.pdf/.docx), 62 officer requests total, each case shipped
  with its author's answer key. The markdown cases are what ship here; the
  .pdf and .docx copies each case was also run against are regenerated
  with `python tests/blind/write_pdf_copies.py <case_dir>` rather than
  committed, since no automated test reads them.
  - Dangerous misses (claiming "answered" where evidence was missing):
    **1 / 62** — the judge over-scored one R-1 request (duty-hour gaps);
    the human gate caught it in review and the drafted document was
    corrected through rejection feedback before export. The checklist
    row itself is the residual risk; the gate is the mitigation.
  - 42/62 exact matches with the answer keys; the rest erred in the
    conservative direction only.
  - Every deliberately planted trap was caught: letterhead-address as
    premises "evidence", payroll registers mimicking tax filings, a
    "patent pending" existing only in a CV, a press table complete except
    its circulation column, itinerary date arithmetic, framework contracts
    expiring before the validity period.
- **Five parser/scoring defects found by blind testing were fixed with
  regression tests:** ITEM-heading notices; a closing "how to respond"
  list mistaken for the requests; PDF text layers (no markdown, CAPS
  headings, wrapped titles swallowing a request's text); bold-numbered
  request lines; `REQUEST N —` headings.
- **Full live run on the hardest blind case (O-1A, 8 requests, PDF
  inputs):** the first draft round misplaced its edits and invented wage
  data — the gate rejected everything, the export verification refused
  the result, and after one tightened instruction the rerun produced 8
  correctly-placed, honest sections through three review rounds (mixed
  approve/reject with feedback, model re-proposal, polish-loop stopped by
  rejecting non-improvements). Final export passed verification.
- **Final full run on an unseen R-1 case, driven through the MCP door**
  (the tool functions an MCP client calls), with the review decisions
  made in the SuperDocs web Review UI — proving the two doors share one
  job and one gate. Two review rounds, rejection feedback honored,
  export passed verification.

## SuperDocs API observations (candidate bug-log material)

- `/v1/users/me` rejects `sk_` keys with 401 (it is a web-session
  endpoint); the documented key check is `GET /v1/sessions`. The 401 is
  easy to misread as a bad key.
- Usage fields, re-probed live on 2026-08-19: `POST /v1/chat` now DOES
  return a full usage block (`ops_charged`, `was_billable`,
  `monthly_used` / `monthly_limit` / `monthly_remaining`,
  `quota_exhausted`) — a judge-style question came back
  `was_billable: false`, `ops_charged: 0`. `POST /v1/chat/async`, the
  endpoint where the drafting money is actually spent, still returns no
  usage block at all, although the API reference (line ~272) promises it
  on every `/chat` and `/chat/async` response. One full
  draft → approve → export run billed exactly 1 operation server-side
  (`monthly_used` 3 → 4) while a usage-only counter read 0 throughout.
  Earlier in this build the block was absent from `/chat` too, so this is
  partially fixed on their side, not fixed. Re-checked 2026-08-24: still
  absent from `/chat/async`, and `/jobs/{id}` carries no charge field
  either; `/chat`'s block now also lists active promotional grants
  (`promotions[].ops_remaining`), which is the bucket actually drawn
  down. A full draft → feedback round → approve → export cycle that day
  cost 1 operation from that grant.
- `GET /v1/attachments/status/{session}`'s `processing_jobs` retains
  completed history; the live signals are `total_processing` /
  `total_ready`.
- `POST /v1/chat` rejects messages over 100,000 characters (422
  string_too_long; re-checked 2026-08-25).
- `POST /v1/documents/export` (markdown) does not return the uploaded
  markdown byte-for-byte. Re-probed 2026-08-25, after SuperDocs' fidelity
  update: code fences now survive (earlier they came back as inline
  code), `*` and similar characters still gain a backslash escape, and a
  `<br>` in a table cell now disappears entirely — the words around it
  come back joined. Words are otherwise preserved; only syntax changes.
- Proposed changes used to expire: a job left `awaiting_approval` for
  about 20 minutes completed on its own with "0 change(s) applied · 5
  change(s) expired unapproved and were NOT applied" (observed
  2026-08-23, 18:15 → 18:35); the API reference did not state this
  lifetime. Re-tested 2026-08-25: a job left awaiting approval was still
  waiting after 40 minutes — the ~20-minute expiry no longer holds.
  Whether changes still expire on a longer clock was not observed.
- Rejecting a proposed change with feedback triggers a re-proposal round;
  rejecting without feedback is a hard stop — matches prior notes, held
  in practice.
