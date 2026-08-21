---
title: "ADR 0007: fixed-interval retries for provisioning jobs"
docsync:
  covers:
    - retry.max_attempts
    - retry.backoff_seconds
    - queue.dead_letter_topic
---

# ADR 0007: fixed-interval retries for provisioning jobs

*Synthetic example document for the docsync extension. Not any real company's
decision record.*

**Status:** accepted
**Date:** 2026-04-22

## Context

Provisioning jobs fail for two reasons that look identical from our side: the
carrier API is briefly unavailable, or the order itself is unfulfillable. The
first resolves on its own within a minute or two. The second never resolves,
and retrying it forever hides a problem that a person needs to see.

## Decision

A provisioning job is attempted up to 3 times before it is abandoned.

Attempts are spaced 30 seconds apart, at a fixed interval rather than an
exponential one. Exponential backoff is the usual answer and it is the wrong
one here: the carrier rate-limits per minute, so a longer wait buys no
additional headroom and only delays the point at which a human finds out.

A job that exhausts its attempts is published to `provisioning.dead-letter`
with the full request and the last response attached. Nothing is retried off
that topic automatically.

## Consequences

The worst case between a first failure and a human being paged is bounded and
short. The cost is that a genuinely slow carrier outage produces dead letters
that a person has to replay by hand, which we accept — replaying is cheap and
a silently stuck queue is not.
