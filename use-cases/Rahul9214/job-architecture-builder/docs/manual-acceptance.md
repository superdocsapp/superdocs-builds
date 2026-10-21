# Manual reviewer acceptance

Observed 2026-08-26 against the production FastAPI UI at `http://127.0.0.1:8010` (port 8000 was already bound by another process). Organization select uses the shared `/api/corpora/{id}` analyze path. No SuperDocs key was configured.

## Northstar Systems (`corpus-a`)

| Step | Observation |
| --- | --- |
| 1. Overview | Heading Overview. Workflow copy present. SuperDocs **not configured**. After analyze (server still had the corpus analyzed), metrics showed 21 total roles. |
| 2. Select Northstar | Organization combobox value Northstar Systems. Banner: 21 source roles. Titles never determine level. |
| 3. Analyze | Analyze corpus. Chip **Analyzed**. Same backend `POST /api/corpora/corpus-a/analyze`. |
| 4. Sources | 21 JD rows including Backend SWE, Workplace Tools, Payments, both Engineering Managers, Developer Advocate, Program Coordinator. |
| 5. Architecture | Metrics and craft neighborhoods. |
| 6. Title vs evidence | Only three cards: Workplace Tools (senior-style vs IC1, provisional); Payments (modest title vs IC4, strong fit); EM Developer Experience (manager-style vs IC track IC3, provisional). Copy states the title was not used to classify. |
| 7. Real Engineering Manager | EM Platform Services appears in the engineering neighborhood, not in Title vs evidence. |
| 8–10. Exceptions | Provisional includes Workplace Tools, EM DX, Solutions Architect, Program Coordinator. Hybrid/bridge: Solutions Architect. Misfit: Developer Advocate, review artifact, requires architecture decision. No auto-assign control. |
| 11–13. Framework | IC1–IC5 and M1–M3 tables. Competency matrices listed per family. Tables use `.table-wrap` horizontal scroll when needed. |
| 14. IC4 profile | Opened Software Engineer II, Payments. Drawer showed Engineering · Individual Contributor · IC4, strong_fit, purpose/responsibilities/level expectations. |
| 15–17. IC4 scope change | Occupied level IC4 v1. Proposed: `Cross-team domain plus an explicit sequencing veto for reviewer acceptance.` Plan result: **2 affected / 16 unaffected** profiles. Unrelated sections listed preserved: autonomy, complexity, impact, leadership, people_management. |
| 18–20. Human review | Mixed decisions: approve Payments plan, reject Staff Product Designer plan. Review outcome **mixed**. After Apply: mutation applied yes, domain applied yes. API check: Payments `level_expectations` contains sequencing veto; Design Systems scope remains `Cross-team domain with multi-quarter bets.` |
| 21. Local export | Export framework wrote `framework.docx` via `local_docx`. Message: SuperDocs was not called. Live SuperDocs export button disabled / not configured. |

## Meridian HealthTech (`corpus-b`)

| Step | Observation |
| --- | --- |
| 1. Switch corpus | Combobox Meridian HealthTech. Banner: 12 source roles. Same shell, no alternate UI. |
| 2. Analyze | `POST /api/corpora/corpus-b/analyze` through the same Analyze corpus control. |
| 3–4. Architecture | Title vs evidence: Principal Engineer, Patient Portal Widgets (senior-style vs IC1) and Site Reliability Engineer, Clinical Cloud (modest title vs IC4). Same typed conflict UI as Northstar. |
| 5–7. Exceptions | Clinical Implementation Architect in hybrid/bridge; Associate, Special Programs provisional/sparse; Medical Science Liaison, Cardiology misfit. |
| 8. Framework / profiles | Framework and profiles load from `/api/framework/corpus-b` and `/api/profiles/corpus-b` (same routes with corpus id). |
| 9. Impact smoke | `POST /api/impact/corpus-b/level-change` with a scope note returned affected=1, unaffected=8, level=IC4. |
| 10. No corpus-specific path | Frontend `api.ts` always uses `/api/.../${corpusId}`. No Meridian-only route or component was observed. |

## Empty / loading / error

- Unanalyzed corpus: empty copy plus Analyze.
- Review with no session: empty “No pending review” (no H1 in that state).
- Analyze button disables while the request runs (not an endless spinner).
- Export live SuperDocs control stays disabled with an explicit not-configured reason.
