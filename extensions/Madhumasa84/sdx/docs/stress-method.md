# Stage 4 stress method

## Fixture construction

`test/stress/generate-docx.mjs` deterministically creates a styled OOXML document with 120 logical pages. It contains 119 explicit Word page breaks, a unique `SDX_PAGE_NNN` marker on each page, headings, body paragraphs, bold/italic/coloured text, lists, tables, a header, a footer with Word page fields, an embedded PNG, and a unique edit target on page 120. ZIP entry timestamps and core-properties timestamps are fixed so repeated generations have identical bytes.

The generator is test-only. `docx` and `jszip` are development dependencies and are not shipped in the published package.

## Page-count verification

The test validates the ZIP container and OOXML structure with `unzip`, counts exactly 119 explicit `w:type="page"` breaks, checks all 120 distinct page markers, and checks the header, footer, media, tables, lists, styles, and page-120 target.

LibreOffice, `soffice`, and another trustworthy DOCX renderer were not available in this environment. Consequently, Stage 4 proves 120 explicitly bounded logical pages but does **not** claim a measured 120-page rendered layout. A rendered page-count check remains an environment-dependent Stage 5 verification item.

## Offline workflow

Each iteration starts a fresh deterministic fixture server and isolated temporary `HOME`, then runs the compiled `sdx` binary as a child process. The workflow requests a pre-signed upload, streams the DOCX to signed PUT, processes it, submits one targeted edit, polls, explicitly approves every proposal, requests DOCX export, streams the signed download to an atomic temporary destination, and verifies the final OOXML and page-120 edited marker.

The fixture records the uploaded byte count and SHA-256 while consuming request chunks. It does not retain the uploaded document body in streaming mode. Tests assert that authorization never reaches signed storage, the API request bodies contain no document bytes or Base64 transport, source and upload hashes match, the source remains unchanged, and failed/partial downloads cannot become the final output.

## Measurements

`npm run test:stress` performs five independent offline iterations. Wall time is measured around the compiled child process with a monotonic clock. Peak resident set size is measured on Linux/WSL by `/usr/bin/time -v` (`Maximum resident set size`, KiB). Input/output byte counts and SHA-256 values are measured from files. Raw sanitized observations and aggregate statistics are written to `docs/evidence/stage4-stress.json`.

For wall time and peak RSS, evidence reports minimum, median, p95, maximum, arithmetic mean, population variance, and population standard deviation. With five samples, the nearest-rank p95 is the maximum; the raw observations are retained so this small-sample limitation is visible. No arbitrary performance or memory threshold is enforced. Structural streaming assertions and honest observed measurements are the acceptance criteria.

Measurements exclude fixture generation but include the complete compiled CLI upload/edit/review/export workflow. Results are offline fixture measurements and are not claims about live SuperDocs latency.
