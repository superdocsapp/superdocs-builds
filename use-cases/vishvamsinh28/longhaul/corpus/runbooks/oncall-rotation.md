# On-Call Rotation Runbook

Owner: Platform Reliability. Review cadence: quarterly. This runbook is fictional and describes Northwind Systems, a company that does not exist.

## Rotation shape

The primary on-call engineer carries the pager for seven days, Monday 10:00 to Monday 10:00 UTC. The secondary covers escalations and takes over if the primary does not acknowledge within five minutes.

## Paging

All alerts route through PagerDuty. The PagerDuty schedule named northwind-primary is the source of truth for who is on call right now; the wiki is not, and has been wrong before.

## Acknowledging a page

Acknowledge in PagerDuty first, then post in #incident-war-room so the rest of the team knows a human has it. Acknowledging without posting is the most common cause of two engineers working the same incident.

## Handover

At the end of a rotation the outgoing primary writes a handover note in #incident-war-room covering open incidents, anything degraded but not paging, and any silenced alerts with their expiry.

## Escalation ladder

Primary, then secondary after five minutes, then the Ops Lead after fifteen. The Ops Lead decides whether to declare a Sev-1 and wake the wider team.
