"""The weekly instruction.

One instruction, one operation, five targeted areas. A SuperDocs operation
covers up to 25 edited sections, so the whole week - status line, three
standing sections, archive row, and an archive rollup when one is due - rides
a single billable call. That is the entire cost argument, and it is why the
archive policy was shaped to fold rows *inside* the weekly edit rather than in
a separate maintenance pass.

The split that matters, and the one to defend out loud:

    FACTS ARE TRANSPORTED. PROSE IS GENERATED.

Everything the digest asserts about the week - what shipped, which risks are
open, what is next - is handed over as **literal HTML** built from the week's
input record. The model is never asked to recall, infer, paraphrase or re-type
a fact, because a paraphrased fact is a fabricated fact and this document is
read by people making schedule decisions.

That is stricter than it started. The first version *described* the target
("replace all bullets with exactly these four") and, measured over seven weeks,
was read as *append* often enough to matter - week 7 came back holding the five
old bullets plus the four new ones. Three rewordings reduced the rate without
removing it, so the factual sections became literal fragments. The full
reasoning is in document.py above bullets_html().

What IS delegated to the model is the genuinely generative part: reading the
sections the document currently holds and compressing them into one archive
row, and folding four old archive rows into one rolled-up row. Those are
summarisation tasks with the source material right there in the document, and
they are exactly what a word processor cannot do.
"""

from __future__ import annotations

from .archive import plan_rows, render_instruction_block
from .document import ArchivePlan, bullets_html, risk_rows_html

PRESERVE = (
    "REPLACEMENT MEANS REPLACEMENT: where this instruction lists what a section "
    "must contain, the section must end up containing exactly that and nothing "
    "else. Delete what is not on the list rather than keeping it alongside.\n"
    "Preserve all existing formatting exactly: the document title, every "
    "section heading, table borders, header-row shading, alternating row "
    "colours, fonts, font sizes and colours. Do not restyle anything. Do not "
    "add, remove or rename any heading. Do not reorder the sections.\n"
    "Copy every quoted or listed value character for character. Do not add a "
    "full stop to a bullet that has none, and do not reword anything.\n"
    "STRUCTURAL RULE: both tables must remain <table> elements with their "
    "header rows intact. Never replace a table with a single row, a div or a "
    "list. Never drop a table's header row."
)


def weekly_instruction(
    week: dict, plan: ArchivePlan, prev_week: dict | None, before_html: str = ""
) -> str:
    """Build the single instruction that advances the digest by one week.

    Step order is load-bearing, learned the expensive way. The status line was
    originally step 2, buried under two archive steps, and week 3 silently
    skipped it (bugs.md B4). It is now the first thing asked for. The archive
    steps still come before the standing sections are overwritten, because the
    archive row is a summary of what those sections currently say.
    """
    steps: list[str] = [
        f"STEP 1 - STATUS LINE. The bold status line directly under the document "
        f"title must read exactly:\n"
        f"  Week {week['week']} · {week['dates']} · Phase: {week['phase']}\n"
        f"Leave the smaller grey line beneath it unchanged."
    ]

    # Archive next, so its summary row captures what the standing sections say
    # BEFORE they are overwritten further down the same instruction.
    if plan.add_row_for_week and prev_week:
        rows, rollup = plan_rows(before_html, prev_week)
        block = render_instruction_block(rows, rollup)
        steps.append(
            f"STEP 2 - ARCHIVE. The 'Archive' table's data rows must end up being "
            f"EXACTLY these {len(rows)} rows, in exactly this order, top to bottom. "
            f"Keep the table's header row and all of its formatting. Cells shown in "
            f"quotes are literal - copy them exactly. Cells shown in angle brackets "
            f"are for you to write.\n{block}"
        )

    steps.append(
        f"STEP 3 - 'What changed'. Replace the ENTIRE <ul> element in that section "
        f"with exactly this HTML, character for character:\n"
        f"{bullets_html(week['shipped'])}"
    )

    closed = (
        f"\n(Context only, do not put this in the document: risks closed this week "
        f"and therefore absent from the rows above: {'; '.join(week['risks_closed'])}.)"
        if week.get("risks_closed") else ""
    )
    steps.append(
        f"STEP 4 - 'What is at risk' table. Replace the ENTIRE contents of that "
        f"table's <tbody> with exactly these {len(week['risks'])} rows, character "
        f"for character. Keep the <thead> header row exactly as it is:\n"
        f"{risk_rows_html(week['risks'])}{closed}"
    )

    steps.append(
        f"STEP 5 - 'What is next'. Replace the ENTIRE <ul> element in that section "
        f"with exactly this HTML, character for character:\n"
        f"{bullets_html(week['next'])}"
    )

    body = "\n\n".join(steps)
    return (
        f"Update this standing weekly production digest to Week {week['week']}. "
        f"This is the same document every week - edit it in place. Make exactly the "
        f"changes below and nothing else.\n\n{body}\n\n{PRESERVE}"
    )


def regenerate_instruction(week: dict, archive_rows: list[dict]) -> str:
    """Control arm: produce the whole digest from scratch, the way a team does
    today when it copies last week's file and rewrites it.

    Same content, same target document, same formatting requirements - the only
    difference is that nothing is edited in place. That is the comparison.
    """
    shipped = "\n".join(f"  - {s}" for s in week["shipped"])
    rows = "\n".join(
        f"  | {r['risk']} | {r['owner']} | {r['area']} | {r['severity']} | {r['trend']} |"
        for r in week["risks"]
    )
    nxt = "\n".join(f"  - {s}" for s in week["next"])
    archive = "\n".join(
        f"  | {a['week']} | {a['dates']} | {a['shipped']} | {a['risks']} |"
        for a in archive_rows
    ) or "  | - | - | Digest opened. No prior weeks. | - |"

    return (
        f"Produce the complete Week {week['week']} production digest for "
        f"Nebula Drift (Vantage Nine Studios) as the whole document, replacing "
        f"whatever is there. Use exactly this structure and content.\n\n"
        f"TITLE (Heading 1): Nebula Drift - Weekly Production Digest\n"
        f"STATUS LINE (bold, directly under the title): "
        f"Week {week['week']} · {week['dates']} · Phase: {week['phase']}\n"
        f"Below it, smaller grey text: Vantage Nine Studios · internal · "
        f"standing document, edited in place every Monday\n\n"
        f"SECTION 'What changed' (Heading 2), as bullets, verbatim:\n{shipped}\n\n"
        f"SECTION 'What is at risk' (Heading 2), as a bordered table with a shaded "
        f"header row and alternating row shading, columns Risk / Owner / Area / "
        f"Severity / Trend:\n{rows}\n\n"
        f"SECTION 'What is next' (Heading 2), as bullets, verbatim:\n{nxt}\n\n"
        f"SECTION 'Archive' (Heading 2), a bordered table with a shaded header row, "
        f"columns Week / Dates / Shipped / Risks carried, newest first:\n{archive}\n\n"
        f"Use the same visual style throughout: dark blue headings, a bordered "
        f"table with a dark shaded header row and alternating light row shading."
    )


def archive_step(week: dict, plan: ArchivePlan, prev_week: dict | None,
                 before_html: str) -> str:
    """Just the archive. The one genuinely generative part of the week."""
    if not (plan.add_row_for_week and prev_week):
        return ""
    rows, rollup = plan_rows(before_html, prev_week)
    return (
        f"In this document's 'Archive' table, the data rows must end up being "
        f"EXACTLY these {len(rows)} rows, in exactly this order, top to bottom. "
        f"Keep the table's header row and all of its formatting. Cells shown in "
        f"quotes are literal - copy them exactly. Cells described in angle "
        f"brackets are for you to write.\n"
        f"{render_instruction_block(rows, rollup)}\n\n"
        f"Change NOTHING else in the document. Do not touch the status line, the "
        f"'What changed' list, the 'What is at risk' table or the 'What is next' "
        f"list.\n{PRESERVE}"
    )


def standing_step(week: dict) -> str:
    """Status line plus the three factual sections, all as literal HTML."""
    return (
        f"Update this weekly digest to Week {week['week']}. Make exactly these "
        f"four changes and nothing else.\n\n"
        f"STEP 1 - STATUS LINE. The bold status line directly under the document "
        f"title must read exactly:\n"
        f"  Week {week['week']} · {week['dates']} · Phase: {week['phase']}\n"
        f"Leave the smaller grey line beneath it unchanged.\n\n"
        f"STEP 2 - the bullet list in the 'What changed' section. Replace that "
        f"<ul> element with exactly this HTML, character for character:\n"
        f"{bullets_html(week['shipped'])}\n\n"
        f"STEP 3 - the 'What is at risk' table. Replace the ENTIRE contents of "
        f"that table's <tbody> with exactly these {len(week['risks'])} rows, "
        f"character for character. Keep its <thead> header row exactly as it is:\n"
        f"{risk_rows_html(week['risks'])}\n\n"
        f"STEP 4 - the bullet list in the 'What is next' section. Replace that "
        f"<ul> element with exactly this HTML, character for character:\n"
        f"{bullets_html(week['next'])}\n\n"
        f"Do not touch the 'Archive' section at all.\n{PRESERVE}"
    )
