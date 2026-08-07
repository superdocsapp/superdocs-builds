"""Generate 52 weeks of synthetic game-production input.

Synthetic on purpose: the brief allows only synthetic or public documents.
*Nebula Drift* and Vantage Nine Studios do not exist. The people do not exist.

Deterministic on purpose too: same seed, same 52 weeks, so anyone can
regenerate the exact corpus the measurement was run on and check my numbers.

The weeks are NOT randomly shuffled noise. They follow a real production arc -
pre-production, vertical slice, alpha, content lock, beta, cert, launch, live
ops - because the point of the build is that a document survives 52 weeks of
*genuine change*. Fifty-two near-identical weeks would prove nothing: drift
appears when the content actually moves.

    python build_corpus.py            # writes weeks.json next to this file
"""

from __future__ import annotations

import json
import random
from pathlib import Path

SEED = 20260807
START_MONDAY = "2026-01-05"

PHASES = [
    (1, 6, "Pre-production"),
    (7, 14, "Vertical Slice"),
    (15, 24, "Alpha"),
    (25, 32, "Content Lock"),
    (33, 40, "Beta"),
    (41, 46, "Certification"),
    (47, 48, "Launch"),
    (49, 52, "Live Ops"),
]

SHIPPED = {
    "Pre-production": [
        "Grapple traversal prototype playable end to end on the test level",
        "Core loop pitch deck signed off by the publisher",
        "Engine upgrade to 5.4 merged; build times down 31%",
        "Art style exploration narrowed to two directions",
        "Nav-mesh generation for the Drift Belt sector",
        "First pass on the Salvage economy spreadsheet",
        "Hired a second combat designer (starts week 9)",
        "Perforce to Git LFS migration completed for the audio depot",
    ],
    "Vertical Slice": [
        "Vertical slice level greyboxed and playable start to finish",
        "Combat prototype merged to main behind a feature flag",
        "Enemy AI flocking behaviour landed for Scrapper swarms",
        "First playtest with eight external players (avg session 41 min)",
        "Audio middleware spike finished; Wwise selected over FMOD",
        "Grapple cooldown retuned from 8s to 5s after playtest data",
        "Cinematic camera rig handed to the animation team",
        "Localisation pipeline stubbed for 6 languages",
    ],
    "Alpha": [
        "All 12 alpha levels blocked out and in the build",
        "Save/load system passes the 500-cycle soak test",
        "Boss encounter 'The Cartographer' first playable",
        "Steam Deck build boots and holds 30 fps on medium",
        "Analytics events wired for the first-hour funnel",
        "Crash rate down to 0.9% of sessions from 4.2%",
        "Photo mode shipped to the internal branch",
        "Accessibility pass one: remappable controls, colourblind palettes",
        "Console TRC pre-check dry run completed",
        "Weapon balance pass across all 9 archetypes",
    ],
    "Content Lock": [
        "Content lock declared for levels 1-9",
        "Final voice-over recorded for the main campaign (2,140 lines)",
        "Art bible frozen at v3.1 and distributed to outsourcers",
        "Narrative branch pruning: 14 dead-end nodes removed",
        "Level streaming budget met on all platforms",
        "Marketing beauty-shot capture session completed",
        "Achievement list finalised at 42 entries",
        "Store page assets delivered to the publisher",
    ],
    "Beta": [
        "Closed beta opened to 2,000 players",
        "Beta week-one retention measured at 38% D1",
        "Top 20 community-reported bugs triaged and 14 fixed",
        "Performance pass: 99th percentile frame time under 22ms",
        "Full localisation QA pass for FIGS complete",
        "Matchmaking backend load-tested to 12k concurrent",
        "Day-one patch scoped and branched",
        "Refund-risk audit on the first-hour experience",
    ],
    "Certification": [
        "First cert submission sent to platform holder A",
        "Cert failure on TRC 0350 fixed and resubmitted",
        "Platform holder B cert passed on first submission",
        "Age rating received: PEGI 12 / ESRB T",
        "Gold master candidate 3 built and archived",
        "Launch-day runbook rehearsed with the live-ops team",
    ],
    "Launch": [
        "Shipped. 84k units sold in the first 72 hours",
        "Launch-day hotfix deployed within 6 hours of a save-corruption report",
    ],
    "Live Ops": [
        "Patch 1.0.2: 31 community bugs closed",
        "First seasonal event 'Ion Storm' live",
        "Player retention D30 measured at 19%",
        "Roadmap for the first paid expansion approved",
        "Post-mortem published internally",
        "Server costs reduced 27% by shrinking the telemetry payload",
    ],
}

RISK_POOL = [
    ("Audio middleware licence not signed", "Priya N.", "Audio"),
    ("Second combat designer starts late", "Marcus O.", "Production"),
    ("Streaming budget overrun on the Drift Belt", "Yuki T.", "Engineering"),
    ("Outsourced character art slipping two weeks", "Priya N.", "Art"),
    ("Console devkit shortage", "Marcus O.", "Production"),
    ("Save-game format still unversioned", "Dev H.", "Engineering"),
    ("Narrative branch count above the VO budget", "Sana R.", "Narrative"),
    ("Steam Deck thermal throttling in the Foundry level", "Yuki T.", "Engineering"),
    ("Crash rate above the cert threshold", "Dev H.", "QA"),
    ("Localisation vendor has no gaming glossary", "Sana R.", "Localisation"),
    ("Matchmaking backend untested above 5k CCU", "Yuki T.", "Backend"),
    ("Publisher marketing beats not aligned with content lock", "Marcus O.", "Production"),
    ("Boss encounter difficulty untuned for controller", "Ana F.", "Design"),
    ("Art bible drifting from the shipped material shaders", "Priya N.", "Art"),
    ("Day-one patch size above the platform cap", "Dev H.", "Engineering"),
    ("No accessibility sign-off for subtitle sizing", "Ana F.", "Design"),
]

NEXT_POOL = {
    "Pre-production": [
        "Lock the art direction to one of the two candidates",
        "Scope the vertical slice level list",
        "Stand up the automated build farm",
        "Decide Wwise vs FMOD",
    ],
    "Vertical Slice": [
        "Get the slice in front of the publisher",
        "Second external playtest, 20 players",
        "Instrument the traversal funnel",
        "Close the audio licence",
    ],
    "Alpha": [
        "Alpha feature freeze review on Thursday",
        "Drive crash rate below 0.5%",
        "Finish the accessibility pass two",
        "Lock the weapon archetype list",
    ],
    "Content Lock": [
        "Declare content lock for levels 10-12",
        "Freeze the narrative graph",
        "Hand the store page to the publisher",
        "Start the cert pre-check checklist",
    ],
    "Beta": [
        "Grow the beta to 5,000 players",
        "Land the day-one patch branch",
        "Close the top 10 community bugs",
        "Finish the localisation QA for CJK",
    ],
    "Certification": [
        "Resubmit to platform holder A",
        "Rehearse the launch runbook end to end",
        "Freeze the gold master candidate",
        "Brief the community team on launch-day comms",
    ],
    "Launch": [
        "Watch the first-hour funnel hourly",
        "Ship the first hotfix if crash rate exceeds 1%",
    ],
    "Live Ops": [
        "Ship patch 1.0.3",
        "Design the second seasonal event",
        "Scope the paid expansion vertical slice",
        "Cut telemetry cost by a further 15%",
    ],
}

SEVERITIES = ["Low", "Medium", "High", "Critical"]
TRENDS = ["improving", "steady", "worsening"]


def phase_for(week: int) -> str:
    for lo, hi, name in PHASES:
        if lo <= week <= hi:
            return name
    return "Live Ops"


def week_dates(week: int) -> str:
    from datetime import date, timedelta

    start = date.fromisoformat(START_MONDAY) + timedelta(weeks=week - 1)
    return f"{start.isoformat()} to {(start + timedelta(days=6)).isoformat()}"


def build() -> list[dict]:
    rng = random.Random(SEED)
    weeks: list[dict] = []
    open_risks: list[dict] = []

    for week in range(1, 53):
        phase = phase_for(week)

        pool = SHIPPED[phase]
        shipped = [pool[(week * 3 + i) % len(pool)] for i in range(rng.randint(2, 4))]
        shipped = list(dict.fromkeys(shipped))

        # Risks persist across weeks, change severity, and get closed - that
        # is what makes week-over-week diffing meaningful.
        closed = []
        for risk in list(open_risks):
            risk["age"] += 1
            if rng.random() < 0.28 or risk["age"] > 6:
                open_risks.remove(risk)
                closed.append(risk["risk"])
            else:
                if rng.random() < 0.45:
                    idx = SEVERITIES.index(risk["severity"])
                    idx = max(0, min(len(SEVERITIES) - 1, idx + rng.choice([-1, 1])))
                    risk["severity"] = SEVERITIES[idx]
                    risk["trend"] = "worsening" if rng.random() < 0.5 else "improving"
                else:
                    risk["trend"] = "steady"

        while len(open_risks) < rng.randint(2, 4):
            name, owner, area = RISK_POOL[(week * 5 + len(open_risks) * 7) % len(RISK_POOL)]
            if any(r["risk"] == name for r in open_risks):
                break
            open_risks.append({
                "risk": name, "owner": owner, "area": area,
                "severity": rng.choice(SEVERITIES[:3]), "trend": "steady", "age": 0,
            })

        nxt_pool = NEXT_POOL[phase]
        nxt = [nxt_pool[(week * 2 + i) % len(nxt_pool)] for i in range(rng.randint(2, 3))]
        nxt = list(dict.fromkeys(nxt))

        weeks.append({
            "week": week,
            "dates": week_dates(week),
            "phase": phase,
            "shipped": shipped,
            "risks": [
                {k: r[k] for k in ("risk", "owner", "area", "severity", "trend")}
                for r in open_risks
            ],
            "risks_closed": closed,
            "next": nxt,
        })
    return weeks


if __name__ == "__main__":
    out = Path(__file__).with_name("weeks.json")
    data = build()
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total_risks = sum(len(w["risks"]) for w in data)
    print(f"wrote {out} - {len(data)} weeks, {total_risks} risk rows, "
          f"{sum(len(w['risks_closed']) for w in data)} closures")
