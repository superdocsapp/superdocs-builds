MAX_TEXT_LENGTH = 20_000


class TextParseError(Exception):
    pass


def parse_text_input(content: str) -> str:
    """Validate and lightly normalize free-form text before AI extraction.

    Handles natural language, pasted emails, and bullet-point input alike -
    the AI extraction step interprets the structure, not this parser.
    """
    if not isinstance(content, str):
        raise TextParseError("Text input must be a string.")

    text = content.strip()
    if not text:
        raise TextParseError("Text input is empty.")
    if len(text) > MAX_TEXT_LENGTH:
        raise TextParseError(f"Text input is too long (max {MAX_TEXT_LENGTH} characters).")

    return text
