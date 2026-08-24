# FINDINGS — SuperDocs bugs we hit and reported

Found while using SuperDocs on real work (a live data-science program plan,
driven end-to-end through both the web app and the MCP API) and while building
clausekeeper against it. Ten open bugs are listed below (seven from the initial
hands-on session of 2026-08-22 plus three from the gated independent repro pass
of 2026-08-23, each reproduced by us). Repro notes name the exact artifact.
Three earlier protocol bugs were fixed by SuperDocs mid-round while we were
still building — we retested them clean on record and credit that below.
Reported via the in-app bug button and the submission form.

## Open — worst first

### BUG-06 · New section numbered for §4 lands at document end · **High**
Asked for "a Rollback Plan subsection under section 4." Got a heading numbered
4.1 appended *after section 9* as the last content block — numbering says
§4.1, placement says last-section. Silent unless you scroll. For an editor
whose whole promise is editing documents in place, placement is the product.
Repro: upload source DOCX → issue the instruction → export → compare outline.

### BUG-07 · Placeholder tables demand info the document already contains · **Medium-High**
With no table requested, two appeared: "Document Control & Addendum — Please
fill: Document ID" (the ID was literally in the document) and a version-history
table claiming v1.1 when the doc's own control block says v1.3. Fabricated
metadata contradicting the source is worse than a crash — users may trust it.
Repro: same session as BUG-06; inspect inserted tables against source metadata.

### BUG-05 · Unrequested edits to untouched sections · **Medium**
Three scoped requests produced a demoted title style (Title → Heading 1),
em-dash spacing churn in two untouched sections, an unsolicited spelling
normalization, and one status bullet duplicated verbatim. Caught only because
we diffed the exported artifact against the source like a paranoid integrator.
Repro: diff exported DOCX vs uploaded source (artifact-level, not chunk-level).

### BUG-10 · Some review cards show no visible change (candidate) · **Medium**
Walking the item-by-item gate, some proposed-change cards rendered empty. An
approval gate you can't read is decoration — it trains users to stop reading
diffs, which is when a bad edit gets through. Suspected cause: change content
arrives as a JSON-encoded string needing a second parse; we suspect the UI
render path hits the same trap we did. Published with caveat: we observed empty
cards but could not pin the exact instruction that produced them; we report the
pattern as observed.

### BUG-04 · Expired download URL fails as raw storage XML · **Low-Medium DX** · reproduced live
Reused a pre-signed export URL after its (documented) 15-minute expiry.
Expected a structured "expired — re-request" error; got raw Google Cloud
Storage `ExpiredToken` XML, HTTP 400. Integrators burn a debug cycle on a
storage error that isn't theirs. The expiry itself is fine; the failure
surface isn't.
Repro: request_download_url → wait >15 min → reuse URL → observe XML.
Captured response committed alongside this file (findings-repro/bug04-expired-redacted.txt — signature redacted, shape kept verbatim).

### BUG-09 · Export filename mangled · **Low-Medium**
Export filename came out `Demand Forecast  Visual Quality Ins.docx` —
ampersand dropped leaving a double space, name truncated around 31 chars.
Trivial fix, daily annoyance.
Repro: export any titled document containing "&".

### BUG-08 · Unrequested footer injection · **Low**
A footer reading "Last Modified: … | Document Control Block | Confidential"
appeared without instruction. In legal/QMS documents, "Confidential" appearing
unbidden is the wrong kind of surprise.
Repro: same session as BUG-06; check exported footer.

### BUG-11 · Sync chat applies immediately with no approval identifier · **High**
Sync POST /v1/chat returned 200 with edits already applied and no job_id / no
awaiting_approval state. No identifier to approve or reject. For an
approval-gated editor, an apply lane without an approval handle is a bypass.
Repro: POST /v1/chat → observe response has no job_id and document already
mutated. Captured in findings-repro/candidate1-sync-chat-no-id.json (redacted).

### BUG-12 · Read staleness window and export-before-apply race · **Medium-High**
Roster/read issued within ~3 s of an apply returned stale content (old hash).
Export requested immediately after apply returned a document without the
just-applied edit. The edit was applied but the export missed it — silent data
loss. Repro: apply → roster at 120 ms (stale) vs 3100 ms (fresh) → export
immediately → diff against source. Captured in findings-repro/candidate2-staleness-export-race.json (redacted).

### BUG-13 · Session upload silently overwrites held document · **Medium**
Re-uploading a document to the same session_id returned 200 with same durable
IDs but replaced content, no version bump or conflict. Caller cannot tell
whether it created or clobbered. Repro: upload file A to session S → upload
file B to same S → fetch durable_id → content is B, no warning. Captured in
findings-repro/candidate3-upload-overwrite.json (redacted).

## Fixed mid-round — credited (retested clean 2026-08-22)

We found these earlier in the round; SuperDocs fixed them while we built.

- **BUG-01** — MCP `tools/list` without `initialize` returned a silent empty
  array. Now returns the full tool catalog. Fixed.
- **BUG-02** — invalid escapes/control characters in the `tools/list` payload
  broke strict JSON parsers. Strict parse over the raw 137,418-byte payload
  now passes. Fixed.
- **BUG-03** — unescaped control characters in async job-poll bodies broke
  strict parsers. Every HTTP body and nested MCP text field now strict-parses
  clean across all polls. Not reproduced.

## Rough edges (not crashes)

- Proposed-change content arrives as a JSON-encoded string needing a second
  parse — documented, but it cost a debug cycle, and we suspect it is also why
  the review UI shows empty cards (BUG-10 above).
- Long operations (30 s – minutes) give no visible progress; "still processing"
  is correct but unknowable from the outside.
- Lane inconsistency worth studying: identical-size asks through MCP produced
  exactly one matching proposed change; the web lane produced spurious extras.

## What works well (earned, not flattery)

Chunked targeted editing genuinely preserved untouched content — our artifact
diff confirmed most regions byte-identical. The item-by-item review gate is
mechanically solid. Exports are free. `llms.txt` and the docs are excellent;
our agents consumed them without friction. Op accounting (`get_account_status`)
made budgeting auditable — a whole four-call exercise billed 1 of 500 free ops,
usage block present at `job.result.usage`.
