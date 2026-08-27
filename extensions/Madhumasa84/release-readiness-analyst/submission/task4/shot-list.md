# Timestamped shot list

Use a 1920×1080 recording with a readable 16–18 pt terminal/browser font. Every frame uses synthetic data and hides machine paths, credentials, signed URLs, and private identifiers.

| Time | Frame/action | On-screen proof | Narration cue |
| --- | --- | --- | --- |
| 0:00–0:20 | Title card, then four synthetic source cards | Requirements, design, test evidence, checklist; user problem | “Release evidence is fragmented; the decision needs traceability.” |
| 0:20–0:35 | Terminal: stdin creation command | `sdx new --title "Q3 review" --export pdf` | “The CLI accepts a pipe and preserves the title.” |
| 0:35–0:45 | File inspector/validator | PDF and DOCX are non-empty and structurally valid | “Offline validation confirms both export paths.” |
| 0:45–0:55 | Terminal JSON output | `schemaVersion: "1.0"`, pending status, exit 3 | “Machine mode is one JSON object and never prompts.” |
| 0:55–1:05 | Terminal diff panel | Heading, change ID, operation, old/new text | “Human mode shows section-level changes.” |
| 1:05–1:25 | Terminal approval | `--accept`, `--reject`; completed result/export | “Every proposal receives one explicit decision.” |
| 1:25–1:45 | Analyst stage timeline | Six stage names, branch marker, completed status | “The durable workflow makes decisions and branches visible.” |
| 1:45–2:05 | Finding detail panel | Source, SHA-256, line range, quote; untrusted-instruction label | “Findings are grounded in cited provenance.” |
| 2:05–2:15 | Decision panel with one pending item | Submit disabled/incomplete warning | “Partial approval cannot silently complete.” |
| 2:15–2:25 | Decision panel after both choices | Approved/rejected feedback and report revision | “The human gate is item-level.” |
| 2:25–2:35 | Fault-injection terminal/timeline | Checkpoint and stopped run ID; no credentials | “The process is interrupted after persistence.” |
| 2:35–2:45 | Restarted timeline | Same run ID resumes at the next stage | “Resume continues the existing run.” |
| 2:45–2:58 | Add synthetic evidence, report diff | New revision; changed dependent finding; unchanged finding ID retained | “Incremental evidence updates only affected sections.” |
| 2:58–3:00 | Final card | `completed`, 6 stages, 3 cited findings, decisions recorded, verdict `blocked` | “The measurable result and limits are explicit.” |

## Capture notes

- Capture the command and the result, not a real home directory or environment dump.
- If a job ID is visible, use a fixture ID such as `job_demo_01`.
- Keep terminal stderr separate from JSON stdout when showing the pipeline.
- Put the limitation card in the final two seconds; do not imply live or rendered-page verification.
