from __future__ import annotations


OBJECTION_PREFIXES = (
    "objection:",
    "obj:",
)

RESPONSE_PREFIXES = (
    "response:",
    "resp:",
    "answer:",
    "ans:",
    "a:",
    "->",
    "→",
)

BULLET_PREFIXES = (
    "-",
    "*",
    "•",
)

# These are presentation headings in our declared input set,
# not objection content.
IGNORED_HEADINGS = {
    "random sales call notes",
    "q4 notes - messy version",
}