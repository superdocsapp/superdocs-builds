---
title: Runbook — circuit activation failures
docsync:
  covers:
    - retry.max_attempts
    - retry.backoff_seconds
    - api.request_timeout_seconds
    - sla.p1_response_minutes
---

# Runbook — circuit activation failures

*Synthetic example document for the docsync extension. Not any real company's
runbook.*

For the on-call engineer. Read the whole thing before acting; most of these
alerts resolve themselves and acting early makes the page fire twice.

## When the activation alert fires

A circuit that has not reached `active` within its window raises a P1. The
response clock for a P1 is 15 minutes, and it starts when the page is sent,
not when you acknowledge it.

## What is already happening without you

The job runs itself again before anyone is paged. It will make three attempts
in total, spaced 30 seconds apart, and only after the last one fails does the
alert reach a human. By the time you are reading this the automatic recovery
has already been tried and has not worked.

Do not re-queue the job as your first action. It has been queued three times
already.

## Checks, in order

1. **Is the carrier API answering at all?** Each call is given 30 seconds
   before we abandon it. A carrier that is merely slow shows up as timeouts
   rather than errors, and the two need different escalations.
2. **Is the order actually fulfillable?** An order missing a site contact or a
   demarcation point will fail identically every time, forever.
3. **Has it dead-lettered?** If it has, the job is no longer running and
   nothing you do to the queue will restart it.

## Escalation

If the carrier API is down, escalate to the carrier's NOC and record the
reference on the incident. Do not keep replaying the job while the carrier is
down — the attempts are wasted and they make the dead-letter topic harder to
read afterwards.
