# docs/

Screenshots of the reviewer UI, captured with Playwright against a demo backend
pointed at **throwaway copies** of the study data — a demo session records
decision events, and running it against `study_data/` would have appended a
fabricated reviewer to the study's append-only event log.

| File | What it shows |
| --- | --- |
| `screenshot-reviewer-ui.png` | The `batch_section` condition: all changes at once, word-level diffs, approve/reject per change, sticky submit bar. Used in the top-level README. |
| `screenshot-change-card.png` | One change close up, so the diff colouring is legible: deletions struck through in red, insertions in green. |
| `screenshot-consent.png` | The consent gate. The study cannot start until it is ticked. |

None of these can leak ground truth: the API never sends labels to the client
(`GROUND_TRUTH_SAFETY.md` GT-1), so there is nothing in the DOM to capture.

The reviewer id shown is `DEMO`, from the throwaway session. Real sessions used
`R1` (discarded pilot run 1) and `R2` (the reported run).
