# Deploy Rollback Runbook

Owner: Delivery Engineering. This runbook is fictional and describes Northwind Systems, a company that does not exist.

## Rollback first, diagnose second

If a deploy correlates with an error-rate rise, roll back. Diagnosis happens after the graph comes down, never before. Nobody has ever regretted a fast rollback.

## How to roll back

Run the pipeline's rollback job against the last known-good tag. If the pipeline itself is broken, deploy the previous image digest directly and note in #incident-war-room that the pipeline was bypassed.

## Database migrations

A deploy carrying a forward-incompatible migration cannot be rolled back by the pipeline. Page the Data Platform on-call through PagerDuty and treat it as a database incident, not a deploy incident.

## Communication

Announce the rollback in #incident-war-room before you start it, not after. A silent rollback during an active incident sends two people chasing the same symptom.

## Verification

Confirm the error rate has returned to baseline for ten consecutive minutes before declaring the rollback successful. The Ops Lead signs off on that call.
