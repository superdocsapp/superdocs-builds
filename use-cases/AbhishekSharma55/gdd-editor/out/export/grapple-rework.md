# Nebula Drift - Grapple Rework (design spike)

Vantage Nine Studios - internal - linked sub-document of the Nebula Drift GDD, section "Traversal - Grapple Rework".

## Problem

The 8 s grapple cooldown is the longest in the game, and playtests show players stop moving while they wait for it. That pause makes traversal feel sticky and breaks momentum.

## Proposed change

The cooldown should drop so the grapple comes back more often. The recovery should move into the animation instead, so the action still has weight without forcing a hard stop.

## Parameters

| Parameter | Current | Proposed | Rationale |
| --- | --- | --- | --- |
| Cooldown | 8 s | 5 s | Reduces idle time so traversal stays responsive |
| Recovery animation | 0.2 s | 0.5 s | Keeps the sense of recovery while moving the lockout into the animation |

## Risks

* Level pacing is currently tuned around the 8 s cadence, so shortening the cooldown may make traversal feel faster than intended.
* Encounter spacing and timing windows may need retuning because the previous 8 s wait created more downtime between moves.
