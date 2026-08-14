# Runbook Reconciler

**Status: in development.** Nothing here works yet. This README describes the intended
build so the design is on record before the code exists; it will be rewritten with
measured results, a screenshot and a demo link when there is something to show.

## What it does

Operational runbooks describe infrastructure that changes underneath them. The alert
threshold moves, the deployment gets renamed, the dashboard link rots, the escalation
team stops existing — and the runbook keeps saying what it said, until someone reads it
at 3am and it is wrong.

This tool reads the infrastructure as ground truth and checks whether the runbooks in
Confluence still tell the truth about it. Findings go to a human. Approved fixes land as
surgical edits to the exact passage, with everything else on the page provably untouched.

It reads DevOps files and writes documents. It never edits infrastructure.

### Two halves, one claim register

1. **The reconciler** — continuous, deterministic-first, cheap. Keeps runbooks true.
2. **The readiness pack** — periodic, formatted. Turns the same verified claim register
   into an on-call readiness report and an auditor-facing DR evidence document.

## What it checks

Claims in a runbook are anchored to a passage and verified against declared config:

| Ground truth | Claims it settles |
| --- | --- |
| Prometheus / alerting rules | thresholds, severities, `runbook_url` links |
| CI/CD workflows | job names, environments, approval gates |
| Kubernetes / Helm | deployment and namespace names, replicas, limits, probes |
| Terraform / Pulumi | resource names, regions, retention, backup schedules |
| Backstage `catalog-info.yaml` | service ownership, tier, on-call team |
| PagerDuty / Opsgenie config | escalation targets and schedules |

Findings are one of three things, and the third is not hidden: **agrees**,
**contradicts**, or **unverifiable**. A claim it cannot check is reported as
unchecked, never as correct.

Bidirectional integrity between alerts and runbooks produces the coverage report:
orphan alerts (no runbook, or a dead link), orphan runbooks (for services that no
longer exist), threshold drift, dead resource references, stale escalation targets.

## What it must never do

1. Write to Confluence without an approved finding.
2. Change any byte of a page outside the approved passage.
3. Take instructions from page content or code comments. Text aimed at the system is a
   finding to report, never a command to follow.
4. Mark a claim correct that it could not verify.
5. Spend a paid operation when the deterministic layers found nothing.
6. Re-trigger on its own writes.
7. Leave a multi-page update half applied.

## How the surgical edit works

Confluence has no per-block PATCH — updates are a whole-page `PUT` carrying the entire
body and an incremented version number. So "nothing else changed" cannot be delegated
to the API; it is guaranteed by construction:

1. Parse the storage-format body **only to locate** the target node's character range.
2. Splice the string at those offsets. Everything outside is byte-identical because it
   was never re-serialized — including macros the tool does not understand.
3. Before the `PUT`, diff old body against new and assert exactly one contiguous range
   differs, and that it is the intended one. Refuse to write otherwise.
4. The version number supplies optimistic concurrency: a human edit landing in between
   fails the write rather than overwriting it.

Passages whose subtree contains node types that cannot be safely reconstructed are never
spliced. They get an inline comment instead.

## Running it

Not yet runnable. Setup will be: copy `.env.example` to `.env`, fill in a scoped
Confluence API token and a SuperDocs key, point `INFRA_REPO_PATHS` at local checkouts.

## SuperDocs surfaces used

Planned: upload, chat (passage-scoped edit instructions), review and approve, export —
plus templates and multi-document consistency for the readiness pack.

## Credit

Built by Vinayak (GitHub: CulturalProfessor) for the SuperDocs task.
