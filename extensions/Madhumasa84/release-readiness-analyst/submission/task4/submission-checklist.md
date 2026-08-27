# Task 4 submission checklist (draft)

The supplied task PDF could not be read because the referenced file was unavailable. “PDF mapping” below is therefore a pending item, never an inferred pass. Confirm the literal PDF and replace the neutral labels before submission.

| Deliverable or requested demonstration element | Draft evidence | Status | Verification / corrective action |
| --- | --- | --- | --- |
| Authoritative PDF read and clause map | Missing source PDF | **BLOCKED** | Obtain the PDF, hash it, read it completely, and map every clause. |
| Three-minute demo; hard five-minute ceiling | `demo-script.md`, `shot-list.md`, `narration.md` | Draft ready | Record a synthetic offline run and time the final master; reject anything over 5:00. |
| User problem | Opening 0:00–0:20 | Draft ready | Keep the release-manager scenario concrete and synthetic. |
| Successful end-to-end workflow | `sdx` stdin/export plus completed analyst run | Evidence available offline | Capture the commands and final status; do not imply shared runtime or live service. |
| Agent stages and branching decisions | Six-stage timeline, missing/contradiction/review branches | Evidence available offline | Capture stage names and branch state from deterministic fixtures. |
| Citations and provenance | Finding source, SHA-256, line range, quote | Evidence available offline | Use fixture names only; hide machine paths. |
| Item-level approval | `sdx approve`; analyst approve/reject/request-evidence | Evidence available offline | Show incomplete guard, mixed decisions, then completed decision set. |
| Interruption and resume | Fault-injection checkpoint and same-run resume | Evidence available offline | State explicitly that this is deterministic offline recovery. |
| Incremental update | New evidence creates report revision; unaffected ID retained | Evidence available offline | Show before/after finding IDs and citation. |
| Measurable outcome | `completed`, six stages, three cited findings, decisions recorded; policy `blocked` | Evidence available offline | Explain that `blocked` is the safe synthetic policy result, not a failed run. |
| One-page project explanation | `project-explanation.md` | Draft ready | Keep to one printed page after PDF layout review. |
| Separate one-page architecture diagram | `architecture-diagram.md` | Draft ready | Render Mermaid to a single page; verify legibility. |
| Four required submission answers | `submission-answers.md` | **PENDING PDF** | Replace neutral headings with exact PDF questions and recheck answers. |
| YouTube copy | `recording-instructions.md` | Not performed | Upload only after user approval; use private/unlisted settings as authorized. |
| Google Drive copy | `recording-instructions.md` | Not performed | Upload only after user approval; restrict access and verify playback. |
| No secrets/private content | Synthetic fixtures; package secret scan | Pass for draft | Re-scan final recording and description; remove any credential or signed URL. |
| No unsupported live claims | Limitations in all package docs | Pass for draft | Preserve statements: zero live operations in current audit, no live cassette, no rendered page count. |
| Exact PDF compliance | Source unavailable | **BLOCKED** | Do not submit until the PDF is accessible and the clause matrix is complete. |

## Final gate before external action

1. Obtain and hash the authoritative PDF.
2. Reconcile exact questions and clause identifiers.
3. Run the offline demo from a clean environment with synthetic content.
4. Record one master under five minutes and visually inspect every frame.
5. Run secret/signed-URL scans on the video notes, description, and package.
6. Obtain explicit approval before making either a YouTube or Google Drive copy.
7. Upload nothing from this draft package automatically.
