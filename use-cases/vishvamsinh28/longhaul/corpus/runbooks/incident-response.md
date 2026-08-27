# Incident Response Runbook

Owner: Platform Reliability. This runbook is fictional and describes Northwind Systems, a company that does not exist.

## Declaring an incident

Anyone can declare. Declaring costs nothing and un-declaring is easy, so declare early. Open PagerDuty, trigger an incident against the affected service, and set the severity you believe applies.

## Severity levels

A Sev-1 is customer-visible loss of a core function with no workaround. A Sev-2 is degraded service or a workaround that customers can reach. A Sev-3 is internal-only impact.

## Roles

Every incident has an Incident Commander, a Communications Lead, and an Operations Lead. One person may hold two roles on a small incident, but the Incident Commander never also runs comms on a Sev-1.

## Communication

The incident channel is #incident-war-room. Status updates go out every thirty minutes on a Sev-1, every hour on a Sev-2, even when the update is that nothing has changed.

## Resolution

Resolve in PagerDuty, post a final update in #incident-war-room, and schedule the review within two business days. The Ops Lead owns the review invitation.
