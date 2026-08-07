"""The graded scenario, run end to end and asserted.

The brief states the bar for this build in one sentence:

    "a reviewer asks for a new GDD section plus one linked sub-document,
     then requests a revision to one mechanic - and only the correct
     section changes across both documents."

This file is that sentence, executable. It is deliberately written as a
sequence of reviewer turns in plain English, because that is what the product
is: a reviewer types, documents change. Everything else here is verification.

    ACT 1  seed the workspace (4 documents, verbatim, free)
    ACT 2  reviewer: "add a Traversal - Grapple Rework section to the GDD,
           and a linked sub-document for it"
    ACT 3  reviewer: "change the Grapple cooldown from 8 s to 5 s"
    ACT 4  prove that across ALL FOUR documents only the intended sections
           moved, and that everything else is byte-identical
    ACT 5  export the workspace

The check in ACT 4 is the whole point, so it is worth being precise about what
it does. It does not ask the API what it changed. It takes a snapshot of every
document's bytes before the turn, and afterwards re-derives, per document, the
set of sections whose own bytes differ - `residue_map` in the kit, so a table
whose cell changed does not count as a changed table. A document nobody named
must come back byte-identical, whole.

Cost: seven billable operations for the full scenario. `--quick` drops the
image act and runs it in five.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from superdocs_kit.docdiff import section_html, table_rows, visible_text

from .corpus import DOCUMENTS
from .images import ensure_demo_images
from .workspace import Workspace

NEW_SECTION = "Traversal - Grapple Rework"
NEW_SUBDOC_KEY = "grapple-rework"
NEW_SUBDOC_TITLE = "Nebula Drift - Grapple Rework (design spike)"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class ScenarioReport:
    checks: list[Check] = field(default_factory=list)
    ops: int = 0
    seconds: float = 0.0
    untouched: dict = field(default_factory=dict)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def render(self) -> str:
        lines = ["", "=" * 78, "GRADED SCENARIO RESULT", "=" * 78]
        for c in self.checks:
            lines.append(f"  [{'PASS' if c.ok else 'FAIL'}] {c.name}"
                         + (f"\n         {c.detail}" if c.detail and not c.ok else ""))
        passed = sum(1 for c in self.checks if c.ok)
        lines += ["-" * 78,
                  f"  {passed}/{len(self.checks)} checks passed  |  "
                  f"{self.ops} operations  |  {self.seconds:.0f}s",
                  "=" * 78, ""]
        return "\n".join(lines)


def _subdoc_seed_html() -> str:
    """The linked sub-document the reviewer asks for, created verbatim.

    Its *content* is then written by the model in ACT 2 - we create the file
    with its heading skeleton so the new document has a known starting state
    and a stable set of chunk ids to diff against. Creating it empty and asking
    the model to invent the whole thing would make ACT 4's "only the intended
    section changed" claim unverifiable for this document.
    """
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>{NEW_SUBDOC_TITLE}</title></head>'
        '<body style="font-family:Inter,Calibri,Arial,sans-serif;color:#212121">'
        f'<h1 style="color:#0d47a1;border-bottom:3px solid #0d47a1;padding-bottom:6px">'
        f'{NEW_SUBDOC_TITLE}</h1>'
        '<p style="background-color:#e3f2fd;border-left:4px solid #1565c0;padding:8px 10px;'
        'font-size:9pt">Vantage Nine Studios - internal - linked sub-document of the '
        'Nebula Drift GDD, section "Traversal - Grapple Rework".</p>'
        '<h2 style="color:#0d47a1">Problem</h2><p>To be written.</p>'
        '<h2 style="color:#0d47a1">Proposed change</h2><p>To be written.</p>'
        '<h2 style="color:#0d47a1">Parameters</h2><p>To be written.</p>'
        '<h2 style="color:#0d47a1">Risks</h2><p>To be written.</p>'
        '</body></html>'
    )


def run(
    ws: Workspace,
    *,
    with_images: bool = True,
    log: Callable[[str], None] = print,
) -> ScenarioReport:
    import time

    rep = ScenarioReport()
    t0 = time.monotonic()

    # ---------------------------------------------------------------- ACT 1
    log("\nACT 1 - seed the workspace (verbatim uploads, no model, free)")
    ws.seed()
    rep.add("workspace seeded with the GDD and three linked sub-documents",
            set(DOCUMENTS) <= set(ws.docs), f"have {sorted(ws.docs)}")
    rep.add("the Grapple cooldown starts at 8 s in Mechanics",
            _cooldown(ws, "mechanics") == "8 s",
            f"found {_cooldown(ws, 'mechanics')!r}")
    rep.add("the GDD's Traversal section also says 8 s",
            "8 s" in visible_text(section_html(ws.docs["gdd"].html, "Traversal")))

    # ---------------------------------------------------------------- ACT 2
    log("\nACT 2 - reviewer: 'add a new GDD section, plus one linked sub-document'")
    snap_a = "before-act-2"
    ws.snapshot(snap_a)

    ws.add_document(NEW_SUBDOC_KEY, NEW_SUBDOC_TITLE, _subdoc_seed_html())

    r_sub = ws.edit(
        NEW_SUBDOC_KEY,
        "Fill in this design spike. Under 'Problem' explain in 2-3 sentences that "
        "the 8 s grapple cooldown is the longest in the game and that playtests "
        "show players stop moving while they wait for it. Under 'Proposed change' "
        "explain in 2-3 sentences that the cooldown drops and the recovery is moved "
        "into the animation instead. Under 'Parameters' put a bordered table with a "
        "shaded header row, columns Parameter / Current / Proposed / Rationale, and "
        "exactly two rows: 'Cooldown' with current '8 s' and proposed '5 s'; "
        "'Recovery animation' with current '0.2 s' and proposed '0.5 s'. Under "
        "'Risks' put two bullets about level pacing being tuned around 8 s. "
        "Change nothing else and keep all existing headings and formatting.",
        label="act2-subdoc",
        expect_sections=["Problem", "Proposed change", "Parameters", "Risks"],
    )
    rep.ops += r_sub.ops
    rep.add("the linked sub-document was authored", r_sub.ok,
            f"unintended: {r_sub.verdict.unintended if r_sub.verdict else ''}")

    r_gdd = ws.edit(
        "gdd",
        f"Add ONE new section to this document, immediately after the existing "
        f"'Traversal' section: a Heading 2 reading exactly '{NEW_SECTION}', "
        f"followed by a single short paragraph saying that a design spike is open "
        f"to reduce the grapple cooldown, and that the full spike lives in the "
        f"linked sub-document '{NEW_SUBDOC_TITLE}'. "
        f"Then add ONE new row to the 'Linked sub-documents' table with cells: "
        f"'Grapple Rework' | 'The grapple cooldown spike' | '{NEW_SECTION}'. "
        f"Do not change any other section, do not change the existing Traversal "
        f"section, and keep all formatting including the table's borders and "
        f"header shading.",
        label="act2-gdd",
        expect_sections=["Linked sub-documents"],
        expect_new_section=True,
    )
    rep.ops += r_gdd.ops
    rep.add(f"the GDD gained the section {NEW_SECTION!r}",
            ws.has_section("gdd", NEW_SECTION),
            f"sections now: {ws.section_names('gdd')}")

    act2 = ws.untouched_report(snap_a, {
        "gdd": ["Linked sub-documents", NEW_SECTION],
    })
    rep.untouched["act-2"] = act2
    rep.add("ACT 2: mechanics, narrative and art-bible are byte-identical",
            all(act2["documents"][k]["ok"] for k in ("mechanics", "narrative", "art-bible")),
            json.dumps({k: act2["documents"][k] for k in
                        ("mechanics", "narrative", "art-bible")})[:400])
    rep.add("ACT 2: nothing else in the GDD moved",
            act2["documents"]["gdd"]["ok"],
            f"unintended: {act2['documents']['gdd'].get('unintended')}")

    # ---------------------------------------------------------------- ACT 3
    log("\nACT 3 - reviewer: 'revise one mechanic - grapple cooldown 8 s -> 5 s'")
    snap_b = "before-act-3"
    ws.snapshot(snap_b)

    r_mech = ws.edit(
        "mechanics",
        "In the 'Grapple' section's parameter table, change the Cooldown value "
        "from '8 s' to '5 s' and update that row's design note to say it is now "
        "paced against the overheat pulse. Change nothing else anywhere in this "
        "document - not the Dash, not the Wall-run, not the Overheat pulse, not "
        "the Salvage economy, and no other row of the Grapple table. Keep every "
        "table's borders, header shading and column widths.",
        label="act3-mechanics",
        expect_sections=["Grapple"],
    )
    rep.ops += r_mech.ops

    r_gdd2 = ws.edit(
        "gdd",
        "In the 'Traversal' section only, change the grapple cooldown from 8 s to "
        "5 s so it matches the Mechanics sub-document. Do not touch any other "
        "section of this document and do not change any other number.",
        label="act3-gdd",
        expect_sections=["Traversal"],
    )
    rep.ops += r_gdd2.ops

    rep.add("Mechanics now says the cooldown is 5 s",
            _cooldown(ws, "mechanics") == "5 s", f"found {_cooldown(ws, 'mechanics')!r}")
    rep.add("the GDD's Traversal prose now says 5 s and no longer says 8 s",
            "5 s" in visible_text(section_html(ws.docs["gdd"].html, "Traversal"))
            and "8 s" not in visible_text(section_html(ws.docs["gdd"].html, "Traversal")),
            visible_text(section_html(ws.docs["gdd"].html, "Traversal"))[:200])

    # ------------------------------------------------------- ACT 4: the bar
    act3 = ws.untouched_report(snap_b, {"mechanics": ["Grapple"], "gdd": ["Traversal"]})
    rep.untouched["act-3"] = act3
    rep.add("ACT 3: ONLY the Grapple section changed in Mechanics",
            act3["documents"]["mechanics"]["ok"],
            f"unintended: {act3['documents']['mechanics'].get('unintended')}")
    rep.add("ACT 3: ONLY the Traversal section changed in the GDD",
            act3["documents"]["gdd"]["ok"],
            f"unintended: {act3['documents']['gdd'].get('unintended')}")
    rep.add("ACT 3: narrative, art-bible and the new sub-document are byte-identical",
            all(act3["documents"][k]["ok"]
                for k in ("narrative", "art-bible", NEW_SUBDOC_KEY)),
            json.dumps({k: act3["documents"][k]
                        for k in ("narrative", "art-bible", NEW_SUBDOC_KEY)})[:400])

    # The other four mechanics must be untouched, checked by value not by hash,
    # because a reader of the report cares about the numbers, not the bytes.
    survivors = {"Dash": "1.2 s", "Wall-run": "2.0 s", "Overheat pulse": "6 s"}
    bad = {
        name: _param(ws, "mechanics", name, "Cooldown" if name != "Wall-run" else "Max duration")
        for name in survivors
    }
    rep.add("the other mechanics' numbers are unchanged",
            all(bad[n] == v for n, v in survivors.items()),
            f"got {bad}, wanted {survivors}")

    # ---------------------------------------------------------------- IMAGES
    if with_images:
        log("\nACT 4b - concept art into the art bible")
        imgs = ensure_demo_images(Path(__file__).resolve().parent.parent / "data" / "images")
        snap_c = "before-images"
        ws.snapshot(snap_c)
        urls = [ws.upload_image(p) for p in imgs.values()]
        r_img = ws.edit(
            "art-bible",
            "In the 'Concept art' section only, add the two images below as an "
            "image each, one after the other, every image followed by a small "
            "italic caption. Caption the first 'Drift Belt exterior - placeholder "
            "plate, approved 2026-02-14' and the second 'Foundry interior - "
            "placeholder plate, approved 2026-02-21'. Change no other section.",
            label="act4-images",
            expect_sections=["Concept art"],
            image_urls=urls,
        )
        rep.ops += r_img.ops
        embedded = ws.docs["art-bible"].html.count("<img")
        rep.add("both concept plates are embedded in the Art Bible", embedded >= 2,
                f"found {embedded} <img> tags")
        img_report = ws.untouched_report(snap_c, {"art-bible": ["Concept art"]})
        rep.untouched["images"] = img_report
        rep.add("embedding images changed nothing but the Concept art section",
                img_report["ok"],
                json.dumps(img_report["documents"])[:400])

    # ---------------------------------------------------------------- ACT 5
    log("\nACT 5 - export the workspace (free)")
    written = ws.export_all("docx")
    rep.add("every document exports to .docx", len(written) == len(ws.docs),
            f"exported {len(written)} of {len(ws.docs)}")
    md = ws.export_all("markdown")
    rep.add("every document exports to Markdown", len(md) == len(ws.docs))

    rep.seconds = time.monotonic() - t0
    return rep


# ---------------------------------------------------------------------------
def _cooldown(ws: Workspace, doc: str) -> str:
    return _param(ws, doc, "Grapple", "Cooldown")


def _param(ws: Workspace, doc: str, section: str, parameter: str) -> str:
    frag = section_html(ws.docs[doc].html, section)
    for row in table_rows(frag):
        if row and row[0].strip().lower() == parameter.lower():
            return row[1].strip() if len(row) > 1 else ""
    return ""
