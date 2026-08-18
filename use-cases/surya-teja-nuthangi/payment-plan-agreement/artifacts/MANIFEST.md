# Artifact manifest

| Artifact | Claim supported | Producer | Shareable | Mode | Git ignored |
|---|---|---|---:|---|---:|
| `live-superdocs-report.json` | Sanitized live async edit, 14 approvals, final verification and 37,329-byte export | `scripts/resume_live_smoke.py` plus manual recovery | Yes | Live, synthetic | No |
| `live/payment-plan-demo.docx` | Valid exported Word package from the verified live run | SuperDocs export endpoint | Yes, synthetic | Live | Yes |
| `browser-smoke-report.json` | Evaluator flow and zero browser-console errors | In-app browser smoke, 2026-08-15 | Yes | Offline | No |
| `screenshots/payment-plan-evaluator-final.png` | Deterministic schedule and zero difference before AI | In-app browser | Yes | Offline | No |
| `screenshots/payment-plan-verifier.png` | Item review and final independent verification | In-app browser | Yes | Offline | No |
| `live-verification-failure.json` | Historical blocked recovery evidence; not a final success result | Resume smoke | Yes, synthetic | Live | No |

The live DOCX is intentionally ignored by the public contribution repository; the sanitized JSON report is the durable, reviewable claim record.
