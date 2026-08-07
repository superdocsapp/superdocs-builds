"""The seed game design documents.

Synthetic. *Nebula Drift* and Vantage Nine Studios do not exist; neither do the
people named. Same fictional universe as the weekly digest in the sibling
folder, deliberately, so one demo narrative carries both builds.

Four documents, because that is how real game teams actually split a GDD once
it stops fitting in one file:

    gdd         the spine - pillars, core loop, one summary section per system,
                and a link table pointing at the sub-documents
    mechanics   the numbers - one stat table per mechanic
    narrative   acts, beats, characters
    art-bible   palette, silhouette rules, concept art

The interesting property for this build is that **the same fact lives in two
documents on purpose**: the Grapple cooldown appears as prose in the GDD's
Traversal section and as a number in the Mechanics stat table. That mirrors how
these documents really drift apart, and it is what makes the graded scenario -
change one mechanic, watch exactly the right sections move in both files - a
real test rather than a staged one.

Every document is uploaded verbatim. Nothing here is authored by a model, so
the starting state is byte-known.
"""

from __future__ import annotations

STUDIO = "Vantage Nine Studios"
GAME = "Nebula Drift"

_H1 = "color:#0d47a1;border-bottom:3px solid #0d47a1;padding-bottom:6px"
_H2 = "color:#0d47a1;margin-top:18px"
_H3 = "color:#1565c0"
_TABLE = ("width:100%;border-collapse:collapse;border:1px solid #37474f;"
          "font-family:Inter,Calibri,Arial,sans-serif;font-size:10pt")
_TH = ("border:1px solid #37474f;background-color:#0d47a1;color:#ffffff;"
       "padding:6px 8px;text-align:left;font-weight:bold")
_TD = "border:1px solid #90a4ae;padding:6px 8px;vertical-align:top"
_NOTE = ("background-color:#e3f2fd;border-left:4px solid #1565c0;"
         "padding:8px 10px;font-size:9pt;color:#37474f")


def _doc(title: str, subtitle: str, body: str) -> str:
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title></head>'
        f'<body style="font-family:Inter,Calibri,Arial,sans-serif;color:#212121">'
        f'<h1 style="{_H1}">{title}</h1>'
        f'<p style="{_NOTE}">{subtitle}</p>'
        f'{body}</body></html>'
    )


def _stat_table(rows: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<tr><td style="{_TD}">{n}</td><td style="{_TD}">{v}</td>'
        f'<td style="{_TD}">{note}</td></tr>'
        for n, v, note in rows
    )
    return (
        f'<table style="{_TABLE}"><thead><tr>'
        f'<th style="{_TH}">Parameter</th><th style="{_TH}">Value</th>'
        f'<th style="{_TH}">Design note</th></tr></thead><tbody>{body}</tbody></table>'
    )


# ---------------------------------------------------------------------------
# 1. The spine
# ---------------------------------------------------------------------------
def gdd_html() -> str:
    body = f"""
<h2 style="{_H2}">Overview</h2>
<p>{GAME} is a single-player momentum-platformer set in the wreckage of a
collapsed orbital shipyard. The player is a salvager who cannot fight most of
what lives there and must out-move it instead.</p>

<h2 style="{_H2}">Design pillars</h2>
<ul>
<li><strong>Momentum is the reward.</strong> Every system either preserves speed or
explains clearly why it took it away.</li>
<li><strong>The wreck remembers.</strong> Sections the player has stripped stay stripped.</li>
<li><strong>Legibility over spectacle.</strong> If a hazard cannot be read in one frame at
speed, it is cut.</li>
</ul>

<h2 style="{_H2}">Core loop</h2>
<ol>
<li>Enter a sector and read its silhouette for salvage.</li>
<li>Route through it without stopping.</li>
<li>Strip what you reached; lose what you did not.</li>
<li>Spend salvage on traversal upgrades, never on combat.</li>
</ol>

<h2 style="{_H2}">Traversal</h2>
<p>Traversal is the game. The player has a dash, a wall-run and a grapple. The
grapple is the only tool that converts height into speed, so it carries the
longest cooldown in the game at <strong>8 s</strong>, and every level is paced
around that number.</p>
<p>Full parameters live in the Mechanics sub-document, section "Grapple".</p>

<h2 style="{_H2}">Combat</h2>
<p>Combat exists to make traversal mistakes expensive. The player has one
defensive tool - an overheat pulse - and no weapons.</p>

<h2 style="{_H2}">Progression</h2>
<p>Salvage buys traversal upgrades in a flat, non-branching order. No skill tree:
the team has shipped one before and it cost six weeks of tuning for no measured
retention gain.</p>

<h2 style="{_H2}">Art direction</h2>
<p>Readable-industrial. Detail lives in silhouette, not surface. Full rules,
palette and reference boards live in the Art Bible sub-document.</p>

<h2 style="{_H2}">Narrative</h2>
<p>Told through the wreck itself and one voice on a dying channel. Beat sheet
and characters live in the Narrative sub-document.</p>

<h2 style="{_H2}">Linked sub-documents</h2>
<table style="{_TABLE}"><thead><tr>
<th style="{_TH}">Sub-document</th><th style="{_TH}">Owns</th>
<th style="{_TH}">Sections in this GDD that depend on it</th>
</tr></thead><tbody>
<tr><td style="{_TD}">Mechanics</td><td style="{_TD}">Every tunable number</td>
<td style="{_TD}">Traversal, Combat, Progression</td></tr>
<tr><td style="{_TD}">Narrative</td><td style="{_TD}">Acts, beats, characters</td>
<td style="{_TD}">Narrative</td></tr>
<tr><td style="{_TD}">Art Bible</td><td style="{_TD}">Palette, silhouette rules, concept art</td>
<td style="{_TD}">Art direction</td></tr>
</tbody></table>

<h2 style="{_H2}">Open questions</h2>
<ul>
<li>Does the overheat pulse need a resource cost, or is the cooldown enough?</li>
<li>Can a sector be re-entered after it is stripped, and does that break pillar 2?</li>
</ul>
"""
    return _doc(f"{GAME} - Game Design Document",
                f"{STUDIO} - internal - the spine. Numbers live in Mechanics; "
                f"do not duplicate them here except as prose.", body)


# ---------------------------------------------------------------------------
# 2. The numbers
# ---------------------------------------------------------------------------
def mechanics_html() -> str:
    body = f"""
<h2 style="{_H2}">How to read this document</h2>
<p style="{_NOTE}">One section per mechanic. Every tunable number in the game
appears here exactly once and is referenced from the GDD as prose. If a number
appears in two places, this one wins.</p>

<h2 style="{_H2}">Dash</h2>
{_stat_table([
    ("Distance", "5.5 m", "Two tiles. Tuned so a dash clears the standard gap."),
    ("Cooldown", "1.2 s", "Short enough to chain, long enough to read."),
    ("I-frames", "0.15 s", "Start of dash only."),
])}

<h2 style="{_H2}">Wall-run</h2>
{_stat_table([
    ("Max duration", "2.0 s", "Falls off rather than stopping dead."),
    ("Speed retained", "85%", "Deliberately lossy: wall-run is a connector, not a route."),
    ("Re-attach window", "0.4 s", "Allows a corner without a full reset."),
])}

<h2 style="{_H2}">Grapple</h2>
{_stat_table([
    ("Range", "18 m", "Reads at speed; longer felt like teleporting."),
    ("Cooldown", "8 s", "The longest cooldown in the game. All level pacing assumes it."),
    ("Speed on release", "140%", "The only system that converts height into speed."),
    ("Attach angle", "60 deg cone", "Forgiving, because the camera is not."),
])}

<h2 style="{_H2}">Overheat pulse</h2>
{_stat_table([
    ("Radius", "4 m", "Defensive only. Never damages."),
    ("Cooldown", "6 s", "Paced against the grapple so they compete."),
    ("Stagger duration", "1.1 s", "Enough to route past, not enough to farm."),
])}

<h2 style="{_H2}">Salvage economy</h2>
{_stat_table([
    ("Base yield per node", "12 units", "Flat. Rarity lives in placement, not in rolls."),
    ("Upgrade cost curve", "60 / 140 / 260", "Three tiers, no branching."),
    ("Decay on death", "0%", "Death costs progress through the sector, not currency."),
])}
"""
    return _doc(f"{GAME} - Mechanics",
                f"{STUDIO} - internal - sub-document of the {GAME} GDD. "
                f"Source of truth for every tunable number.", body)


# ---------------------------------------------------------------------------
# 3. The story
# ---------------------------------------------------------------------------
def narrative_html() -> str:
    body = f"""
<h2 style="{_H2}">Premise</h2>
<p>The Drift Belt was a shipyard until it was not. Nobody agrees on what
happened and the only person still transmitting has a reason to lie.</p>

<h2 style="{_H2}">Act I - Salvage</h2>
<p>The player learns to move. Vex, on the channel, is helpful and slightly too
well informed about a place she claims never to have visited.</p>

<h2 style="{_H2}">Act II - The Cartographer</h2>
<p>The wreck has been mapped before. The player starts finding the map, and it
is annotated in Vex's hand.</p>

<h2 style="{_H2}">Act III - Drift</h2>
<p>The player can leave or finish the map. Both endings are short; neither is
the "good" one.</p>

<h2 style="{_H2}">Characters</h2>
<table style="{_TABLE}"><thead><tr>
<th style="{_TH}">Character</th><th style="{_TH}">Role</th><th style="{_TH}">Voice</th>
</tr></thead><tbody>
<tr><td style="{_TD}">The Salvager</td><td style="{_TD}">Player</td>
<td style="{_TD}">Silent. Reads as competent, not heroic.</td></tr>
<tr><td style="{_TD}">Vex</td><td style="{_TD}">Voice on the channel</td>
<td style="{_TD}">Warm, funny, unreliable.</td></tr>
<tr><td style="{_TD}">The Cartographer</td><td style="{_TD}">Antagonist, absent</td>
<td style="{_TD}">Never speaks. Only annotations.</td></tr>
</tbody></table>
"""
    return _doc(f"{GAME} - Narrative",
                f"{STUDIO} - internal - sub-document of the {GAME} GDD.", body)


# ---------------------------------------------------------------------------
# 4. The look
# ---------------------------------------------------------------------------
def art_bible_html() -> str:
    body = f"""
<h2 style="{_H2}">Silhouette rules</h2>
<ul>
<li>Every hazard must be identifiable as a black shape at 40 px.</li>
<li>Traversable geometry is warm; lethal geometry is cold. No exceptions.</li>
<li>Detail budget goes to edges, not surfaces.</li>
</ul>

<h2 style="{_H2}">Palette</h2>
<table style="{_TABLE}"><thead><tr>
<th style="{_TH}">Role</th><th style="{_TH}">Hex</th><th style="{_TH}">Used for</th>
</tr></thead><tbody>
<tr><td style="{_TD}">Traversable</td><td style="{_TD}">#E8A33D</td>
<td style="{_TD}">Ledges, grapple points, anything the player may touch</td></tr>
<tr><td style="{_TD}">Lethal</td><td style="{_TD}">#3D6FE8</td>
<td style="{_TD}">Coolant, vacuum breaches, crushers</td></tr>
<tr><td style="{_TD}">Neutral hull</td><td style="{_TD}">#37474F</td>
<td style="{_TD}">Everything else</td></tr>
</tbody></table>

<h2 style="{_H2}">Concept art</h2>
<p>Reference boards live in this section. Each image is captioned with the
sector it belongs to and the date it was approved.</p>
"""
    return _doc(f"{GAME} - Art Bible",
                f"{STUDIO} - internal - sub-document of the {GAME} GDD.", body)


DOCUMENTS: dict[str, tuple[str, str]] = {
    "gdd": ("Nebula Drift - Game Design Document", gdd_html()),
    "mechanics": ("Nebula Drift - Mechanics", mechanics_html()),
    "narrative": ("Nebula Drift - Narrative", narrative_html()),
    "art-bible": ("Nebula Drift - Art Bible", art_bible_html()),
}

# The link graph, kept as data rather than inferred from prose. Adding a
# sub-document is a change to this dict and nothing else - the workspace, the
# link table in the GDD and the cross-document checks all read from here.
LINKS: dict[str, dict] = {
    "mechanics": {"owns": "Every tunable number",
                  "gdd_sections": ["Traversal", "Combat", "Progression"]},
    "narrative": {"owns": "Acts, beats, characters", "gdd_sections": ["Narrative"]},
    "art-bible": {"owns": "Palette, silhouette rules, concept art",
                  "gdd_sections": ["Art direction"]},
}
