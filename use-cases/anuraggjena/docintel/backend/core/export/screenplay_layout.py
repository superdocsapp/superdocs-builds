"""
Centralized Screenplay Layout and Spacing Configuration.

Defines standard industry-standard screenplay dimensions, indentations,
and context-aware spacing rules for both DOCX and PDF exporters.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ScreenplayLayoutConfig:
    # Page setup (Inches)
    page_width_in: float = 8.5
    page_height_in: float = 11.0
    margin_left_in: float = 1.5
    margin_right_in: float = 1.0
    margin_top_in: float = 1.0
    margin_bottom_in: float = 1.0

    # Typography
    font_name_docx: str = "Courier New"
    font_name_pdf: str = "Courier"
    font_name_pdf_bold: str = "Courier-Bold"
    font_size_pt: float = 12.0
    line_spacing: float = 1.0
    leading_pt: float = 14.4

    # Indentations (Inches from left margin)
    scene_heading_left_in: float = 0.0
    scene_heading_right_in: float = 0.0

    action_left_in: float = 0.0
    action_right_in: float = 0.0

    character_left_in: float = 2.0
    character_right_in: float = 0.0

    parenthetical_left_in: float = 1.5
    parenthetical_right_in: float = 2.0

    dialogue_left_in: float = 1.0
    dialogue_right_in: float = 1.5

    shot_left_in: float = 0.0
    shot_right_in: float = 0.0

    # Vertical Spacing (Points)
    title_space_before: float = 0.0
    title_space_after: float = 6.0

    author_space_before: float = 0.0
    author_space_after: float = 24.0

    scene_heading_space_before: float = 18.0
    scene_heading_space_after: float = 12.0

    action_space_before: float = 0.0
    action_space_after: float = 12.0

    # Dialogue block internal spacing (tight / compact)
    character_space_before: float = 0.0
    character_space_after: float = 0.0

    parenthetical_space_before: float = 0.0
    parenthetical_space_after: float = 0.0

    dialogue_space_before: float = 0.0
    dialogue_continue_space_after: float = 0.0
    dialogue_end_space_after: float = 12.0

    transition_space_before: float = 12.0
    transition_space_after: float = 12.0

    shot_space_before: float = 12.0
    shot_space_after: float = 6.0

    end_space_before: float = 24.0
    end_space_after: float = 12.0


DEFAULT_SCREENPLAY_LAYOUT = ScreenplayLayoutConfig()


def calculate_element_spacing(
    element_type: str,
    prev_type: Optional[str] = None,
    next_type: Optional[str] = None,
    config: ScreenplayLayoutConfig = DEFAULT_SCREENPLAY_LAYOUT,
) -> Tuple[float, float]:
    """
    Calculate (space_before, space_after) in points for a screenplay element
    based on its context (preceding and succeeding elements).

    Ensures:
      - Character -> Parenthetical -> Dialogue blocks are compact (0pt internal gap).
      - Multi-line dialogue from the same character remains grouped (0pt gap).
      - Action paragraphs and separate character speeches maintain 12pt standard spacing.
      - Scene headings maintain 18pt before and 12pt after.
    """
    if element_type == "title":
        return config.title_space_before, config.title_space_after

    if element_type in ("author", "author_credit", "credit"):
        return config.author_space_before, config.author_space_after

    if element_type == "scene_heading":
        space_before = config.scene_heading_space_before if prev_type is not None else 0.0
        return space_before, config.scene_heading_space_after

    if element_type == "character":
        # Character cue has 0 space_after so following paren/dialogue is immediately attached.
        # space_before is 0 when preceding element (action/dialogue/heading) already provides 12pt+.
        space_before = 12.0 if prev_type in ("title", "author", "author_credit", "credit", None) else 0.0
        return space_before, config.character_space_after

    if element_type == "parenthetical":
        # Compact inside dialogue block
        return config.parenthetical_space_before, config.parenthetical_space_after

    if element_type == "dialogue":
        space_before = config.dialogue_space_before
        # If continuing to another parenthetical or dialogue in same speech:
        if next_type in ("parenthetical", "dialogue"):
            space_after = config.dialogue_continue_space_after
        elif next_type in ("scene_heading", "end"):
            # Next heading/end will supply its own larger space_before
            space_after = 0.0
        else:
            space_after = config.dialogue_end_space_after
        return space_before, space_after

    if element_type == "transition":
        space_before = 12.0 if prev_type in ("title", "author", None) else 0.0
        space_after = 0.0 if next_type in ("scene_heading", "end") else config.transition_space_after
        return space_before, space_after

    if element_type == "shot":
        space_before = 12.0 if prev_type in ("title", "author", None) else 0.0
        space_after = config.shot_space_after
        return space_before, space_after

    if element_type == "end":
        return config.end_space_before, config.end_space_after

    # Default / Action
    space_before = config.action_space_before
    space_after = 0.0 if next_type in ("scene_heading", "end") else config.action_space_after
    return space_before, space_after
