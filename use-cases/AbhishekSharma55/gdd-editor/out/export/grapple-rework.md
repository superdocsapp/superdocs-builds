# Nebula Drift - Grapple Rework (design spike)

Vantage Nine Studios - internal - linked sub-document of the Nebula Drift GDD, section "Traversal - Grapple Rework".

## Problem

The 8 s grapple cooldown is the longest in the game, and playtests show players stop moving while they wait for it. That pause makes traversal feel sluggish compared with the rest of the kit.

## Proposed change

Drop the cooldown and move the recovery into the animation instead, so the ability becomes available sooner while the end of the move still carries some commitment. This keeps the feel of recovery without forcing a long dead stop after each grapple.

## Parameters

| Parameter | Current | Proposed | Rationale |
| --- | --- | --- | --- |
| Cooldown | 8 s | 5 s | Shortens the longest cooldown in the game to keep movement flowing |
| Recovery animation | 0.2 s | 0.5 s | Moves the recovery beat into the animation instead of the post-use wait |

## Risks

* Level design is optimized for an 8-second pacing cadence.
* This 8-second interval ensures consistent player engagement throughout the stage.
