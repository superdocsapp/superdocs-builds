import re
from dataclasses import dataclass, field
from typing import List, Optional
from backend.logging_config import get_logger

logger = get_logger(__name__)

TRANSITIONS = {
    "CUT TO:", "FADE OUT.", "FADE IN:", "DISSOLVE TO:", "SMASH CUT TO:",
    "MATCH CUT TO:", "IRIS OUT.", "IRIS IN.", "WIPE TO:", "FADE TO BLACK.",
    "FADE OUT", "CUT TO BLACK.", "BACK TO:", "JUMP CUT TO:",
    "INTERCUT WITH:", "INTERCUT:", "INTERCUT", "END FLASHBACK.", "END FLASHBACK",
    "FLASHBACK", "END MONTAGE.", "END MONTAGE", "MONTAGE", "LATER - DAY",
    "LATER - NIGHT", "LATER", "MOMENTS LATER", "CONTINUOUS", "SAME TIME",
    "BACK TO SCENE.", "BACK TO SCENE",
}

SCENE_PATTERN = re.compile(r"^(INT\.|EXT\.|INT\./EXT\.|EXT\./INT\.|I/E\.|EST\.)\s+.+", re.IGNORECASE)
AUTHOR_PATTERN = re.compile(r"^(written by|by|screenplay by|story by|teleplay by|author:|credit:)\s+.+", re.IGNORECASE)
END_PATTERN = re.compile(r"^(the end|end|fin|f\.i\.n\.)\.?$", re.IGNORECASE)
PAGE_NUMBER_PATTERN = re.compile(r"^(\d+\.|\bpage\s+\d+|\bp\.\s*\d+|\b\d+\b)$", re.IGNORECASE)
SHOT_PATTERN = re.compile(r"^(ANGLE ON|CLOSE ON|CLOSE UP|WIDE SHOT|POV|INSERT|ESTABLISHING SHOT|AERIAL SHOT|TRACKING SHOT|PAN TO|ZOOM IN|ZOOM OUT|EXTREME CLOSE UP|ECU|CU|WS|MOVING SHOT|HANDHELD)\b.*", re.IGNORECASE)
TRANSITION_PATTERN = re.compile(r"^(CUT TO:|FADE OUT\.|FADE IN:|DISSOLVE TO:|SMASH CUT TO:|MATCH CUT TO:|IRIS OUT\.|IRIS IN\.|WIPE TO:|FADE TO BLACK\.|FADE OUT|CUT TO BLACK\.|BACK TO:|JUMP CUT TO:|INTERCUT WITH:|INTERCUT:|END FLASHBACK\.|END FLASHBACK|END MONTAGE\.|END MONTAGE|LATER\b.*|MOMENTS LATER\b.*|CONTINUOUS\b.*|SAME TIME\b.*)$", re.IGNORECASE)
CHARACTER_PATTERN = re.compile(r"^[A-Z][A-Z0-9\s\.\-\'\&/\(\)\#]+$")
ANNOTATION_PATTERN = re.compile(
    r"\s*(?:[-–—]+\s*|\s*[\(\[\{]\s*|\s*(?:\/\*|\/\/|#)\s*)(?:no\s+parens?|missing\s+parens?(?:\s+here)?|missing\s+parenthetical|add\s+parens?|no\s+parentheses|missing\s+parens|missing\s+parenthesis)\s*[\)\]\}]?",
    re.IGNORECASE,
)


@dataclass
class ScreenplayElement:
    element_type: str        # title, author, scene_heading, action, character, dialogue, parenthetical, transition, shot, page_number, end, uncertain
    content: str
    element_index: int
    scene_number: Optional[int] = None
    character_name: Optional[str] = None
    confidence: float = 1.0


class ScreenplayParser:
    """
    Line-by-line state machine parser for screenplay text.

    Distinguishes:
    - TITLE
    - AUTHOR / CREDIT
    - SCENE_HEADING
    - ACTION
    - CHARACTER (verified by structural lookahead to dialogue/parenthetical)
    - PARENTHETICAL
    - DIALOGUE
    - TRANSITION
    - SHOT
    - PAGE_NUMBER
    - END / TERMINATION
    - OTHER / UNCERTAIN
    """

    def parse(self, text: str) -> List[ScreenplayElement]:
        if not text or not text.strip():
            return []

        lines = text.splitlines()
        elements: List[ScreenplayElement] = []
        index = 0
        scene_number = 0
        state = "neutral"          # neutral | in_character_block
        current_character: Optional[str] = None
        seen_scene_heading = False
        i = 0

        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Skip blank lines — they reset character block state
            if not stripped:
                if state == "in_character_block":
                    state = "neutral"
                    current_character = None
                i += 1
                continue

            # Title & Author / Credit detection before first scene heading
            if not seen_scene_heading:
                if AUTHOR_PATTERN.match(stripped):
                    elements.append(ScreenplayElement(
                        element_type="author",
                        content=stripped,
                        element_index=index,
                        confidence=1.0,
                    ))
                    index += 1
                    i += 1
                    continue

                if (i + 1 < len(lines) and any(AUTHOR_PATTERN.match(lines[k].strip()) for k in range(i + 1, min(i + 4, len(lines))))) or (index == 0 and not SCENE_PATTERN.match(stripped)):
                    elements.append(ScreenplayElement(
                        element_type="title",
                        content=stripped,
                        element_index=index,
                        confidence=1.0,
                    ))
                    index += 1
                    i += 1
                    continue

            # Page number
            if PAGE_NUMBER_PATTERN.match(stripped) and len(stripped) <= 10:
                elements.append(ScreenplayElement(
                    element_type="page_number",
                    content=stripped,
                    element_index=index,
                    confidence=1.0,
                ))
                index += 1
                state = "neutral"
                current_character = None
                i += 1
                continue

            # Scene heading
            if SCENE_PATTERN.match(stripped):
                seen_scene_heading = True
                scene_number += 1
                elements.append(ScreenplayElement(
                    element_type="scene_heading",
                    content=stripped,
                    element_index=index,
                    scene_number=scene_number,
                    confidence=1.0,
                ))
                index += 1
                state = "neutral"
                current_character = None
                i += 1
                continue

            # End marker
            if END_PATTERN.match(stripped):
                elements.append(ScreenplayElement(
                    element_type="end",
                    content=stripped,
                    element_index=index,
                    confidence=1.0,
                ))
                index += 1
                state = "neutral"
                current_character = None
                i += 1
                continue

            # Transition
            if stripped.upper() in {t.upper() for t in TRANSITIONS} or TRANSITION_PATTERN.match(stripped):
                elements.append(ScreenplayElement(
                    element_type="transition",
                    content=stripped,
                    element_index=index,
                    confidence=1.0,
                ))
                index += 1
                state = "neutral"
                current_character = None
                i += 1
                continue

            # Shot
            if SHOT_PATTERN.match(stripped) and len(stripped) <= 60:
                elements.append(ScreenplayElement(
                    element_type="shot",
                    content=stripped,
                    element_index=index,
                    scene_number=scene_number if scene_number > 0 else None,
                    confidence=0.9,
                ))
                index += 1
                state = "neutral"
                current_character = None
                i += 1
                continue

            # Character cue: all-caps / character pattern, not ending with punctuation
            # Structural validation: lookahead to verify that next non-blank line is dialogue or parenthetical
            if (stripped == stripped.upper()
                    and 1 < len(stripped) <= 40
                    and not stripped.endswith(":")
                    and not stripped.endswith(".")
                    and not stripped.endswith("?")
                    and not stripped.endswith("!")
                    and stripped.upper() not in {t.upper() for t in TRANSITIONS}
                    and not TRANSITION_PATTERN.match(stripped)
                    and not SCENE_PATTERN.match(stripped)
                    and not END_PATTERN.match(stripped)
                    and not SHOT_PATTERN.match(stripped)
                    and not PAGE_NUMBER_PATTERN.match(stripped)
                    and CHARACTER_PATTERN.match(stripped)):
                
                # Check previous line was blank, top of scene, or previous element was dialogue/parenthetical/action
                prev_blank = (i == 0) or (not lines[i - 1].strip())
                prev_is_character_context = (state == "in_character_block") or prev_blank or (len(elements) > 0 and elements[-1].element_type in ("dialogue", "parenthetical", "scene_heading", "action"))
                
                # Lookahead to find next non-blank line
                next_non_blank = None
                for k in range(i + 1, len(lines)):
                    if lines[k].strip():
                        next_non_blank = lines[k].strip()
                        break

                # Verify next line is dialogue or parenthetical, and NOT a scene/transition/end/shot
                is_followed_by_dialogue = False
                if next_non_blank:
                    is_next_scene = bool(SCENE_PATTERN.match(next_non_blank))
                    is_next_trans = (next_non_blank.upper() in {t.upper() for t in TRANSITIONS}) or bool(TRANSITION_PATTERN.match(next_non_blank))
                    is_next_end = bool(END_PATTERN.match(next_non_blank))
                    is_next_shot = bool(SHOT_PATTERN.match(next_non_blank))
                    is_next_page = bool(PAGE_NUMBER_PATTERN.match(next_non_blank))
                    is_next_author = bool(AUTHOR_PATTERN.match(next_non_blank))

                    if not (is_next_scene or is_next_trans or is_next_end or is_next_shot or is_next_page or is_next_author):
                        # Next line is a valid dialogue or parenthetical line if parenthetical or contains lowercase/spoken text
                        if (next_non_blank.startswith("(") and next_non_blank.endswith(")")) or any(c.islower() for c in next_non_blank):
                            is_followed_by_dialogue = True

                if prev_is_character_context and is_followed_by_dialogue:
                    state = "in_character_block"
                    # Clean character cue for character_name (remove (V.O.), (O.S.), (CONT'D), etc.)
                    clean_char_name = re.sub(r"\s*\(.*?\)", "", stripped).strip()
                    current_character = clean_char_name or stripped
                    elements.append(ScreenplayElement(
                        element_type="character",
                        content=stripped,
                        element_index=index,
                        scene_number=scene_number if scene_number > 0 else None,
                        character_name=current_character,
                        confidence=0.95,
                    ))
                    index += 1
                    i += 1
                    continue

            # Parenthetical with parentheses (in character block or standalone parenthetical)
            if stripped.startswith("(") and stripped.endswith(")"):
                if state == "in_character_block":
                    cleaned_inner = ANNOTATION_PATTERN.sub("", stripped[1:-1]).strip()
                    elements.append(ScreenplayElement(
                        element_type="parenthetical",
                        content=f"({cleaned_inner})",
                        element_index=index,
                        scene_number=scene_number if scene_number > 0 else None,
                        character_name=current_character,
                        confidence=1.0,
                    ))
                    index += 1
                    i += 1
                    continue

            # In character block — check for action cue / parenthetical with formatting annotations
            if state == "in_character_block":
                if ANNOTATION_PATTERN.search(stripped):
                    cleaned_text = ANNOTATION_PATTERN.sub("", stripped).strip()
                    if cleaned_text:
                        elements.append(ScreenplayElement(
                            element_type="parenthetical",
                            content=f"({cleaned_text.strip('()')})",
                            element_index=index,
                            scene_number=scene_number if scene_number > 0 else None,
                            character_name=current_character,
                            confidence=1.0,
                        ))
                        index += 1
                        i += 1
                        continue

                # Dialogue line in character block
                elements.append(ScreenplayElement(
                    element_type="dialogue",
                    content=stripped,
                    element_index=index,
                    scene_number=scene_number if scene_number > 0 else None,
                    character_name=current_character,
                    confidence=1.0,
                ))
                index += 1
                i += 1
                continue

            # Action block — default for unmatched non-empty line in neutral state
            cleaned_action = ANNOTATION_PATTERN.sub("", stripped).strip() if ANNOTATION_PATTERN.search(stripped) else stripped
            confidence = 0.85 if not cleaned_action.isupper() else 0.6
            elem_type = "action" if confidence >= 0.7 else "uncertain"
            elements.append(ScreenplayElement(
                element_type=elem_type,
                content=cleaned_action,
                element_index=index,
                scene_number=scene_number if scene_number > 0 else None,
                confidence=confidence,
            ))
            index += 1
            i += 1

        logger.info("screenplay_parsed", element_count=len(elements), scene_count=scene_number)
        return elements
