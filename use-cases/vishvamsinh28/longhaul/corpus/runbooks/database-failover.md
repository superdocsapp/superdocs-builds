# Database Failover Runbook

Owner: Data Platform. This runbook is fictional and describes Northwind Systems, a company that does not exist.

## When to fail over

Fail over when the primary has been unreachable for more than ninety seconds, or when replication lag on the primary exceeds five minutes and is climbing. Do not fail over for a single failed health check.

## Before you start

Page the Data Platform secondary through PagerDuty and get a second pair of eyes before touching anything. Failover is not a solo operation, at any hour.

## The procedure

Freeze writes at the proxy, confirm the replica has caught up, promote the replica, repoint the proxy, then unfreeze. Record the time of each step in #incident-war-room as you go.

## After failover

The old primary stays down until someone has read its logs. Bringing it back automatically has caused split-brain twice, both times at night, both times worse than the original outage.

## Escalation

If the promotion fails, escalate to the Ops Lead immediately and declare a Sev-1. Do not attempt a second promotion without the Ops Lead on the call.
