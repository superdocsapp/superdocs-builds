# Nebula Drift - Mechanics

Vantage Nine Studios - internal - sub-document of the Nebula Drift GDD. Source of truth for every tunable number.

## How to read this document

One section per mechanic. Every tunable number in the game
appears here exactly once and is referenced from the GDD as prose. If a number
appears in two places, this one wins.

## Dash

| Parameter | Value | Design note |
| --- | --- | --- |
| Distance | 5.5 m | Two tiles. Tuned so a dash clears the standard gap. |
| Cooldown | 1.2 s | Short enough to chain, long enough to read. |
| I-frames | 0.15 s | Start of dash only. |

## Wall-run

| Parameter | Value | Design note |
| --- | --- | --- |
| Max duration | 2.0 s | Falls off rather than stopping dead. |
| Speed retained | 85% | Deliberately lossy: wall-run is a connector, not a route. |
| Re-attach window | 0.4 s | Allows a corner without a full reset. |

## Grapple

| Parameter | Value | Design note |
| --- | --- | --- |
| Range | 18 m | Reads at speed; longer felt like teleporting. |
| Cooldown | 5 s | It is now paced against the overheat pulse. |
| Speed on release | 140% | The only system that converts height into speed. |
| Attach angle | 60 deg cone | Forgiving, because the camera is not. |

## Overheat pulse

| Parameter | Value | Design note |
| --- | --- | --- |
| Radius | 4 m | Defensive only. Never damages. |
| Cooldown | 6 s | Paced against the grapple so they compete. |
| Stagger duration | 1.1 s | Enough to route past, not enough to farm. |

## Salvage economy

| Parameter | Value | Design note |
| --- | --- | --- |
| Base yield per node | 12 units | Flat. Rarity lives in placement, not in rolls. |
| Upgrade cost curve | 60 / 140 / 260 | Three tiers, no branching. |
| Decay on death | 0% | Death costs progress through the sector, not currency. |
