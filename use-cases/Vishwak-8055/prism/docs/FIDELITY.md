# Fidelity Report

Per the directive: "If fidelity cannot be proven: UNVERIFIED, not
VERIFIED." This document states what's actually proven.

| Aspect | Proven? | Evidence |
|---|---|---|
| Paragraph text survives an unmodified round-trip | Yes | `write-docx.test.js` "round-trips ... byte-for-byte in content", independently checked via `pandoc` |
| A real content mutation is correctly written and nothing else changes | Yes | `write-docx.test.js` "applies a real content change" |
| Bold run formatting survives a round-trip | Yes | `write-docx.test.js` "preserves bold formatting" |
| Styles/fonts/theme/settings survive (not just paragraph text) | Proven by construction, not by direct inspection | `writeDocx` never touches any zip entry except `word/document.xml`; not independently verified by, e.g., opening the output in real Word/LibreOffice and inspecting styles visually |
| `<w:sectPr>` (page setup) survives | Proven by construction | Spread-preserved from the source body object, not regenerated; not independently re-verified by parsing the output's sectPr back out in a test |
| Table content survives | Yes, when write doesn't also change paragraph count | `write-docx.test.js` "preserves a table verbatim" + "anchors multiple tables at different positions", independently confirmed via `pandoc` (this is also where a real bug was caught: an early version silently stripped table attributes like column width — pandoc rendering the table as missing was the signal, not a failing assertion) |
| Table structure (merges, cell text) matches after write-back | Yes | `@prism/grid` tests against real gridSpan/vMerge fixtures; `@prism/ui`'s end-to-end test confirms a real PASS through the full compare→apply flow |
| Table content survives when the same write also adds/removes paragraphs | **No — refused, not attempted** | `write-docx.test.js` "refuses only the genuinely ambiguous case"; see KNOWN_LIMITATIONS #2a |
| A full approve/reject/edit cycle produces exactly the approved mutation set | Yes | `gate.test.js` "partial approval", verified two independent ways (direct inspection + re-running PRISM DELTA on the result) |
| Version restoration matches the original content exactly | Yes | `vault.test.js`, including a deliberate-tamper test proving the check isn't a no-op |
| Fidelity at document scale (50+ pages) | **Not tested** | Fixtures are two short contracts; no claim of fidelity at scale is made |
| Fidelity for documents originally created in real Microsoft Word (vs. this session's `docx`-package-generated fixtures) | **Not tested** | All fixtures were generated with the `docx` npm package; real Word documents can contain constructs (compatibility settings, revision save IDs, complex field codes) this hasn't been exercised against |

## What "VERIFIED" means in this codebase, concretely

Only one place in this codebase uses the word programmatically:
`compose.js`'s workflow, where `VERIFIED` requires re-running PRISM DELTA
against the applied output and getting an exact expected count. That is a
real, narrow, tested guarantee — not a general claim that "the document is
preserved." The table above is the honest broader picture.
