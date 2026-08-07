# Nebula Drift - Grapple Rework (design spike)

Vantage Nine Studios - internal - linked sub-document of the Nebula Drift GDD, section "Traversal - Grapple Rework".

## Problem

The 8 s grapple cooldown is the longest in the game, and playtests show players stop moving while they wait for it. That pause breaks momentum and makes the grapple feel slower than the rest of the movement kit.

## Proposed change

Reduce the cooldown and move the recovery into the animation instead, so the grapple still feels committed without leaving players idle. This keeps the action readable while getting players back into movement sooner.

## Parameters

| Parameter | Current | Proposed | Rationale |
| --- | --- | --- | --- |
| Cooldown | 8 s | 5 s | Reduces idle waiting without losing commitment. |
| Recovery animation | 0.2 s | 0.5 s | Moves the pause into the animation so flow resumes sooner. |

## Risks

* Level pacing may need retuning because some spaces were tuned around the current 8 s wait.
* Traversal and combat spacing may feel denser because the level rhythm was built around that 8 s cooldown.
