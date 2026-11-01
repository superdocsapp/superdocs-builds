# Task 2 submission checklist

## Local quality gate

- [ ] `npm install` succeeds from a fresh clone
- [ ] `npm run verify:all` passes
- [ ] `.env` is ignored and no secret is committed
- [ ] `npm start` opens the review UI
- [ ] TXT/Markdown manuscript works
- [ ] DOCX manuscript works
- [ ] PDF manuscript works for text-based PDFs
- [ ] HTML manuscript works
- [ ] ordinary sentence-starting words are not flooded into the term review queue
- [ ] human term approval changes enforceable DNT rules
- [ ] packet includes source, term base, pronunciation, meaning, DNT, style, formatting, instructions, metadata
- [ ] bad translation produces actionable chapter findings
- [ ] good translation produces zero findings in the second-manuscript demo

## SuperDocs live gate

- [ ] `SUPERDOCS_API_KEY` is present locally only
- [ ] UI connection check succeeds
- [ ] `npm run demo:superdocs` succeeds when a live key is intentionally configured
- [ ] packet HTML reaches SuperDocs
- [ ] proposed changes appear in UI
- [ ] approve/reject is explicit
- [ ] DOCX export succeeds
- [ ] `data-chunk-id` anchors survive the round trip

Do not claim the live gate is complete until every checkbox above has been actually exercised.
