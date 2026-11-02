from engine.response_skeleton import DRAFT_PLACEHOLDER_PREFIX


def build_draft_instruction() -> str:
    """The one chat message that turns the skeleton into a draft.

    A tested artefact: tests pin the constraints below, so changing this
    prompt deliberately breaks a test instead of silently shipping.
    """
    return (
        "This document is a draft response to an immigration Request for "
        "Evidence. Each section headed 'Response to Request N' contains one "
        "paragraph whose ENTIRE text is a placeholder of the form "
        f"'{DRAFT_PLACEHOLDER_PREFIX} RN — TO BE WRITTEN]'. Replace each such "
        "placeholder paragraph — and ONLY those paragraphs — with response "
        "prose, following every rule below.\n"
        "Rules:\n"
        "1. Edit a paragraph only if its entire current text is one of the "
        "placeholders. Never edit the paragraphs that begin with "
        "\"Officer's request\", 'Petition material relied on', or "
        "'Evidence gap' — they are read-only inputs, and altering a quoted "
        "officer request falsifies the record.\n"
        "2. Address the officer's stated concern quoted in that section "
        "directly. Do not restate the petition material as the answer.\n"
        "3. Use ONLY the petition material quoted in that same section. Do "
        "not add any fact, date, number, name, exhibit, or document that "
        "is not in the quoted material. Never claim that evidence, data, "
        "or an exhibit exists unless it is quoted in that section.\n"
        "4. Where the section shows an 'Evidence gap' note, the response "
        "must plainly say the evidence is not yet provided and will follow "
        "upon attorney confirmation. Never write as if the missing "
        "evidence exists.\n"
        "5. Do not change the Coverage checklist table or the 'Exhibit "
        "set' section.\n"
        "6. Keep each response to one to three paragraphs of plain, formal "
        "English.\n"
        "7. The original petition documents are attached to this session. "
        "You may search them to confirm context, but every fact you write "
        "must still appear in the material quoted in that section — the "
        "attachments never license a new claim."
    )
