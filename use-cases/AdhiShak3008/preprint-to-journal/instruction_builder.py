"""
instruction_builder.py
Build the natural-language transformation instruction sent to SuperDocs
from a journal profile dict.

The instruction is designed to:
  - Restructure the document to match the journal's section order
  - Reformat references to the journal's citation style
  - Move figures and tables to the required placement
  - Apply blinding when required
  - Add or flag required declarations
  - Enforce word limits where possible
  - Explicitly prohibit rewriting scientific content

Configuration drives behaviour: adding a new journal profile with different
values produces a different instruction without any code changes.
"""

from blinding import build_blinding_instruction


SCIENCE_PRESERVATION_PREAMBLE = """
CRITICAL CONSTRAINT — SCIENTIFIC CONTENT MUST NOT BE CHANGED:
You must not rewrite, paraphrase, summarise, or alter any scientific claims,
numerical results, statistical values (p-values, confidence intervals, effect
sizes, sample sizes), equations, or the meaning of any citation. Do not invent
references or alter citation targets. The transformation changes only document
structure, section order, reference formatting style, and placement of figures
and tables. Every number, every equation, every scientific claim must appear
in the output exactly as it appears in the input.
""".strip()


def build_instruction(profile, author_info=None):
    """
    Build the full transformation instruction for a given journal profile.

    profile: dict loaded by journal_loader.load_profile()
    author_info: optional dict with keys 'names' (list) and 'affiliations' (list)
                 used to build blinding instructions when required.

    Returns a single instruction string to pass as the 'message' to SuperDocs.
    """
    parts = [SCIENCE_PRESERVATION_PREAMBLE, ""]
    parts.append(
        f"Transform this manuscript to meet the submission requirements of "
        f"**{profile['name']}**. Apply the following changes:"
    )
    parts.append("")

    # 1. Section order
    section_list = "\n".join(
        f"  {i+1}. {s}" for i, s in enumerate(profile["section_order"])
    )
    parts.append(
        f"**1. Section structure and order**\n"
        f"Reorganise the manuscript so its sections appear in this exact order:\n"
        f"{section_list}\n"
        f"Rename existing sections to match these headings exactly. "
        f"If a section does not exist in the manuscript, note it as missing "
        f"rather than inventing content."
    )

    # 2. Reference style
    ref_desc = profile.get(
        "reference_style_description",
        profile.get("reference_style", "")
    )
    parts.append(
        f"**2. Reference formatting**\n"
        f"Reformat all in-text citations and the reference list to use the "
        f"{profile['name']} style: {ref_desc}\n"
        f"Do not add, remove, or alter any reference. Only reformat the "
        f"citation style."
    )

    # 3. Figure placement
    fig_desc = profile.get(
        "figure_placement_description",
        profile.get("figure_placement", "")
    )
    parts.append(
        f"**3. Figure placement**\n"
        f"Move all figures and figure legends to: {fig_desc}"
    )

    # 4. Table placement
    tbl_desc = profile.get(
        "table_placement_description",
        profile.get("table_placement", "")
    )
    parts.append(
        f"**4. Table placement**\n"
        f"Move all tables to: {tbl_desc}"
    )

    # 5. Word limit
    word_limit = profile.get("word_limit")
    abstract_limit = profile.get("abstract_word_limit")
    if word_limit:
        parts.append(
            f"**5. Word limit**\n"
            f"The main text word limit is {word_limit} words "
            f"(excluding abstract, methods, references, and figure legends). "
            f"If the manuscript exceeds this limit, flag the excess clearly "
            f"with a comment such as '[WORD LIMIT: manuscript currently exceeds "
            f"{word_limit} words — manual reduction required]' at the start of "
            f"the document. Do not delete scientific content to meet the limit."
        )
    if abstract_limit:
        abstract_structure = profile.get("abstract_structure")
        if abstract_structure:
            subheadings = ", ".join(abstract_structure)
            parts.append(
                f"**Abstract structure**\n"
                f"Restructure the abstract to include these subheadings: "
                f"{subheadings}. The abstract must not exceed {abstract_limit} words. "
                f"Do not alter the scientific content of the abstract."
            )
        else:
            parts.append(
                f"**Abstract**\n"
                f"The abstract must not exceed {abstract_limit} words. "
                f"Do not alter the scientific content."
            )

    # 6. Required declarations
    declarations = profile.get("required_declarations", [])
    decl_descriptions = profile.get("declaration_descriptions", {})
    if declarations:
        decl_list = []
        for decl in declarations:
            desc = decl_descriptions.get(decl, decl.replace("_", " ").title())
            decl_list.append(f"  - **{decl.replace('_', ' ').title()}**: {desc}")
        decl_block = "\n".join(decl_list)
        parts.append(
            f"**6. Required declarations**\n"
            f"Check whether the following declarations are present. "
            f"If a declaration section exists, move it to the correct position "
            f"in the section order. If it is missing, insert a placeholder "
            f"section with the text '[DECLARATION REQUIRED — please complete "
            f"before submission]':\n{decl_block}"
        )

    # 7. Journal-specific notes
    notes = profile.get("notes")
    if notes:
        parts.append(
            f"**7. Additional journal requirements**\n{notes}"
        )

    # 8. Blinding (only when required)
    if profile.get("blinded_review"):
        blinding_instruction = build_blinding_instruction(author_info)
        parts.append(blinding_instruction)

    parts.append("")
    parts.append(
        "After completing all transformations, do not add any commentary or "
        "explanation inside the document body. The output should be the "
        "transformed manuscript only."
    )

    return "\n\n".join(parts)
