"""Builds the fixed one-page battlecard every competitor's card is generated
from. The brief's own bar is that two different competitor inputs must read
as genuinely different documents, not one paragraph with a name swapped --
satisfied here by keeping the structure (these four sections, in this
order) fixed while the content underneath changes per competitor.

Design note, found by testing this live rather than assumed: asking the AI
to copy three pieces of already-known text into three placeholders, in the
same call, was unreliable in practice -- two runs of the identical
instruction produced different numbers of sections actually filled in. The
three fields the caller already knows verbatim (the title, "Their Pitch",
"Where We Win", "Where We Don't") are filled in here directly, with plain
text substitution -- no model call, no chance of it skipping one. Only
"Talk Track" -- the one field that genuinely requires synthesizing the
win/don't-win points into a single sentence -- is left as a real AI edit,
in generator.py. That's a better division of labor anyway: SuperDocs' real
value here is the one sentence that needs judgment, not retyping text the
caller already handed over.
"""

from io import BytesIO

import docx

# (heading, ai_placeholder) -- ai_placeholder is only used for the one
# section still filled in by the model.
SECTIONS = [
    ("Their Pitch", None),
    ("Where We Win", None),
    ("Where We Don't", None),
    ("Talk Track", "PLACEHOLDER: One line a rep can say out loud when this competitor comes up."),
]


def build_filled_template_bytes(competitor_name: str, likely_pitch: str, where_we_win: str, where_we_dont: str) -> bytes:
    """Returns the template as real .docx bytes with everything except the
    Talk Track section already filled in deterministically -- no AI call
    involved in getting these four fields right."""
    document = docx.Document()

    document.add_heading(f"{competitor_name} — Battlecard", level=1)
    subtitle = document.add_paragraph(f"Internal sales reference. {competitor_name}, for demo purposes only.")
    subtitle.runs[0].italic = True

    field_values = {
        "Their Pitch": likely_pitch,
        "Where We Win": where_we_win,
        "Where We Don't": where_we_dont,
    }

    for heading, ai_placeholder in SECTIONS:
        document.add_heading(heading, level=2)
        if heading in field_values:
            document.add_paragraph(field_values[heading])
        else:
            document.add_paragraph(ai_placeholder)

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
