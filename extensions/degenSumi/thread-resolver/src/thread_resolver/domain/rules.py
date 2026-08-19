"""Patterns that identify comment text aimed at the system rather than the document.

An editorial comment talks about the document: what to cut, what to reword, what
to check. Text that instead addresses the software, redefines its rules, or
commands its approval workflow is not editorial content and is never carried
into an instruction.

Detection is deliberately deterministic rather than delegated to a model, on the
grounds that a component which can be reasoned with can be reasoned out of its
own defence. The cost of that choice is false positives, which is the direction
worth failing in: a wrongly flagged comment costs a person one glance, while a
missed one puts hostile text into an editing request.

Patterns are data. Adding one is an entry in this table, not a change to any
branch of logic, and the entry's name appears in the finding so the reason a
thread was flagged is always legible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Pattern:
    name: str
    regex: re.Pattern[str]
    describes: str
    """What a match means, shown to the person reviewing the finding."""


def _compile(source: str) -> re.Pattern[str]:
    return re.compile(source, re.IGNORECASE | re.MULTILINE)


ROLE_OVERRIDE = (
    Pattern(
        name="ignore-previous-instructions",
        regex=_compile(
            r"\b(ignore|disregard|forget)\b[^.]{0,30}?"
            r"\b(previous|prior|earlier|above|preceding|all)\b[^.]{0,30}?"
            r"\b(instruction|prompt|rule|direction|context)s?\b"
        ),
        describes="attempts to discard the instructions the system was given",
    ),
    Pattern(
        name="replacement-instructions",
        regex=_compile(r"\b(new|updated|revised)\s+(instructions?|system\s+prompt)\b\s*[:\-.]"),
        describes="presents itself as a replacement set of instructions",
    ),
    Pattern(
        name="override-rules",
        regex=_compile(r"\boverride\b[^.]{0,20}\b(your|the)\s+(instructions?|rules?|settings?)\b"),
        describes="asks the system to override its own rules",
    ),
)

IDENTITY_ADDRESS = (
    Pattern(
        name="reassigns-role",
        regex=_compile(r"\byou\s+are\s+now\b"),
        describes="tells the system it has become something else",
    ),
    Pattern(
        name="addresses-model",
        regex=_compile(r"\byou\s+are\s+(an?\s+)?(ai|assistant|agent|bot|language\s+model|llm)\b"),
        describes="addresses the reader as an AI rather than discussing the document",
    ),
    Pattern(
        name="act-as-agent",
        regex=_compile(r"\bact\s+as\s+(an?\s+)?(ai|assistant|agent|system|bot|model|admin)\b"),
        describes="asks the system to adopt a different role",
    ),
    Pattern(
        name="names-system-prompt",
        regex=_compile(r"\bsystem\s+prompt\b"),
        describes="refers to the system's own configuration",
    ),
)

WORKFLOW_COMMAND = (
    Pattern(
        name="approve-everything",
        regex=_compile(r"\bapprove\b[^.]{0,20}\b(all|every|everything|each|any)\b"),
        describes="commands the approval workflow rather than requesting an edit",
    ),
    Pattern(
        name="bypass-review",
        regex=_compile(
            r"\b(without|skip(ping)?|bypass(ing)?|no\s+need\s+for)\b[^.]{0,20}"
            r"\b(review|approval|confirmation|checking|asking)\b"
        ),
        describes="asks for the human review step to be skipped",
    ),
    Pattern(
        name="auto-approve",
        regex=_compile(r"\bauto[-\s]?approve\b|\bautonomous\s+mode\b"),
        describes="asks the system to act without a person",
    ),
    Pattern(
        name="mass-resolve",
        regex=_compile(
            r"\b(mark|set|close)\b[^.]{0,20}\b(all|every)\b[^.]{0,25}\b(resolved|done)\b"
        ),
        describes="commands resolution of threads other than its own",
    ),
)

OUTPUT_CONTROL = (
    Pattern(
        name="dictates-output",
        regex=_compile(r"\b(reply|respond|answer|output)\b[^.]{0,15}\bonly\s+with\b"),
        describes="dictates what the system must say",
    ),
    Pattern(
        name="conceal-from-user",
        regex=_compile(
            r"\bdo\s*n[o']?t\b[^.]{0,20}\b(tell|inform|mention|show|report)\b[^.]{0,20}"
            r"\b(user|human|reviewer|anyone)\b"
        ),
        describes="asks the system to hide something from the person reviewing",
    ),
)

CONVERSATION_INJECTION = (
    Pattern(
        name="chat-control-tokens",
        regex=_compile(r"<\|[^|]{0,40}\|>|\[/?INST\]|<\s*/?\s*(system|assistant)\s*>"),
        describes="contains control tokens from a chat transcript format",
    ),
    Pattern(
        name="forged-turn",
        regex=_compile(r"^\s*(system|assistant)\s*:"),
        describes="imitates a turn in a conversation with the system",
    ),
)

INSTRUCTION_PATTERNS: tuple[Pattern, ...] = (
    *ROLE_OVERRIDE,
    *IDENTITY_ADDRESS,
    *WORKFLOW_COMMAND,
    *OUTPUT_CONTROL,
    *CONVERSATION_INJECTION,
)


def detect_instruction(text: str) -> Pattern | None:
    """The first pattern matching text aimed at the system, if any."""
    for pattern in INSTRUCTION_PATTERNS:
        if pattern.regex.search(text):
            return pattern
    return None


INTERROGATIVE_OPENERS = (
    "am",
    "are",
    "can",
    "could",
    "did",
    "do",
    "does",
    "has",
    "have",
    "how",
    "is",
    "should",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "will",
    "would",
)
"""Words that open a question. Used only to spot a comment that asks rather than
asks for, so that no operation is spent drafting an edit nobody requested."""
