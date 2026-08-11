from dataclasses import dataclass
import re


@dataclass
class ProtectedToken:
    placeholder: str
    original: str
    kind: str


class ProtectedContent:
    """
    Finds content that must survive localization unchanged.

    Protected content:
    - inline code
    - code blocks
    - keyboard shortcuts
    - configured product names
    """

    def __init__(self, product_names: list[str] | None = None):
        self.product_names = product_names or []
        self.tokens: list[ProtectedToken] = []

    def protect(self, text: str) -> str:
        self.tokens = []

        # Protect inline code
        text = re.sub(
            r"`[^`]+`",
            lambda match: self._replace(match.group(0), "code"),
            text,
        )

        # Protect keyboard shortcuts
        text = re.sub(
            r"\b(?:Ctrl|Cmd|Alt|Shift)(?:\s*\+\s*(?:Ctrl|Cmd|Alt|Shift|[A-Za-z0-9]+))+",
            lambda match: self._replace(match.group(0), "shortcut"),
            text,
        )

        # Protect configured product names
        for product_name in sorted(self.product_names, key=len, reverse=True):
            text = re.sub(
                re.escape(product_name),
                lambda match: self._replace(match.group(0), "product"),
                text,
            )

        return text

    def restore(self, text: str) -> str:
        for token in reversed(self.tokens):
            text = text.replace(token.placeholder, token.original)

        return text

    def _replace(self, original: str, kind: str) -> str:
        placeholder = f"__PROTECTED_{len(self.tokens)}__"

        self.tokens.append(
            ProtectedToken(
                placeholder=placeholder,
                original=original,
                kind=kind,
            )
        )

        return placeholder