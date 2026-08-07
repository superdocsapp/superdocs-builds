# Nebula Drift - Game Design Document

Vantage Nine Studios - internal - the spine. Numbers live in Mechanics; do not duplicate them here except as prose.

## Overview

Nebula Drift is a single-player momentum-platformer set in the wreckage of a
collapsed orbital shipyard. The player is a salvager who cannot fight most of
what lives there and must out-move it instead.

## Design pillars

* **Momentum is the reward.** Every system either preserves speed or
  explains clearly why it took it away.
* **The wreck remembers.** Sections the player has stripped stay stripped.
* **Legibility over spectacle.** If a hazard cannot be read in one frame at
  speed, it is cut.

## Core loop

1. Enter a sector and read its silhouette for salvage.
2. Route through it without stopping.
3. Strip what you reached; lose what you did not.
4. Spend salvage on traversal upgrades, never on combat.

## Traversal

Traversal is the game. The player has a dash, a wall-run and a grapple. The
grapple is the only tool that converts height into speed, so it carries the
longest cooldown in the game at **5 s**, and every level is paced
around that number.

Full parameters live in the Mechanics sub-document, section "Grapple".

## Traversal - Grapple Rework

A design spike is open to reduce the grapple cooldown. The full spike lives in the linked sub-document "Nebula Drift - Grapple Rework (design spike)".

## Combat

Combat exists to make traversal mistakes expensive. The player has one
defensive tool - an overheat pulse - and no weapons.

## Progression

Salvage buys traversal upgrades in a flat, non-branching order. No skill tree:
the team has shipped one before and it cost six weeks of tuning for no measured
retention gain.

## Art direction

Readable-industrial. Detail lives in silhouette, not surface. Full rules,
palette and reference boards live in the Art Bible sub-document.

## Narrative

Told through the wreck itself and one voice on a dying channel. Beat sheet
and characters live in the Narrative sub-document.

## Linked sub-documents

| Sub-document | Owns | Sections in this GDD that depend on it |
| --- | --- | --- |
| Mechanics | Every tunable number | Traversal, Combat, Progression |
| Narrative | Acts, beats, characters | Narrative |
| Art Bible | Palette, silhouette rules, concept art | Art direction |
| Grapple Rework | The grapple cooldown spike | Traversal - Grapple Rework |

## Open questions

* Does the overheat pulse need a resource cost, or is the cooldown enough?
* Can a sector be re-entered after it is stripped, and does that break pillar 2?
