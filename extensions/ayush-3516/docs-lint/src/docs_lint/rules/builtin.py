"""The built-in rule set.

These are the mechanical rules: things with a right answer that never varies, that cost nothing to
check, and that a model should not be asked about. Anything requiring judgement — tone, structure,
whether a paragraph actually explains the thing it claims to explain — belongs to the SuperDocs
pass instead.

Every rule's severity and options are overridable from `docs-lint.toml`. The defaults here are a
starting house style, not a decree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, ClassVar

from ..model import Finding, Severity
from ..parser import Document, SegmentKind
from .base import RuleBase, register

# Words that legitimately stay capitalised mid-heading. Extended via rule options.
DEFAULT_PROPER_NOUNS = (
    "API",
    "APIs",
    "CI",
    "CLI",
    "CSS",
    "HTML",
    "HTTP",
    "HTTPS",
    "JSON",
    "JSX",
    "MDX",
    "SDK",
    "SQL",
    "SSH",
    "TOML",
    "URL",
    "URLs",
    "UUID",
    "XML",
    "YAML",
    "GitHub",
    "GitLab",
    "Docker",
    "Kubernetes",
    "Python",
    "JavaScript",
    "TypeScript",
    "Markdown",
    "Node",
    "React",
    "Linux",
    "macOS",
    "Windows",
    "SuperDocs",
    "I",
)

DEFAULT_BANNED_TERMS = {
    "utilise": "use",
    "utilize": "use",
    "leverage": "use",
    "in order to": "to",
    "at this point in time": "now",
    "a large number of": "many",
}


def _word_pattern(term: str) -> re.Pattern[str]:
    """Match a term on word boundaries, case-insensitively, allowing flexible inner spacing."""
    parts = [re.escape(part) for part in term.split()]
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b", re.IGNORECASE)


def _match_case(original: str, replacement: str) -> str:
    """Carry the original's capitalisation onto the replacement.

    Without this, fixing "Utilise the API" produces "use the API" mid-sentence and the fix
    introduces a new error. A rule whose correction needs a follow-up correction is not a fix.
    """
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


@register
class BannedTerms(RuleBase):
    """Words the house style forbids, with the preferred word to use instead."""

    rule_id: ClassVar[str] = "banned-terms"
    default_severity: ClassVar[Severity] = Severity.ERROR
    description: ClassVar[str] = "Flags words the style guide bans and proposes the preferred term."

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        terms = options.get("terms")
        if not isinstance(terms, dict) or not terms:
            terms = DEFAULT_BANNED_TERMS

        for segment in document.prose_segments:
            for term, preferred in terms.items():
                if not isinstance(term, str) or not isinstance(preferred, str):
                    continue
                for match in _word_pattern(term).finditer(segment.raw):
                    found = match.group(0)
                    start = segment.start_offset + match.start()
                    end = segment.start_offset + match.end()
                    yield self.finding(
                        severity=self.default_severity,
                        message=f"Avoid {found!r}; the style guide prefers {preferred!r}.",
                        anchor=document.anchor(segment, start=start, end=end),
                        original=found,
                        replacement=_match_case(found, preferred),
                    )


@register
class HeadingCase(RuleBase):
    """Headings in sentence case: first word capitalised, the rest lower unless proper nouns."""

    rule_id: ClassVar[str] = "heading-case"
    default_severity: ClassVar[Severity] = Severity.WARNING
    description: ClassVar[str] = "Requires sentence-case headings rather than Title Case."

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        if str(options.get("style", "sentence")).lower() != "sentence":
            return  # only sentence case is implemented; any other value disables the rule
        allowed = set(DEFAULT_PROPER_NOUNS) | {
            str(word) for word in options.get("proper_nouns", []) if isinstance(word, str)
        }

        for segment in document.segments:
            if segment.kind is not SegmentKind.HEADING:
                continue
            words = segment.content.split()
            if len(words) < 2:
                continue

            offenders = [
                word
                for word in words[1:]
                if word[:1].isupper() and word.strip(".,:;!?()[]") not in allowed
            ]
            # One stray capital is often a proper noun this rule does not know about. Two or more
            # is Title Case. Requiring a majority avoids the false positives that get a rule
            # switched off entirely, which would cost more than it saves.
            if len(offenders) < 2:
                continue

            fixed = self._to_sentence_case(words, allowed)
            start = segment.start_offset + segment.content_offset
            yield self.finding(
                severity=self.default_severity,
                message=f"Heading looks like Title Case; sentence case reads {fixed!r}.",
                anchor=document.anchor(segment, start=start, end=start + len(segment.content)),
                original=segment.content,
                replacement=fixed,
                explanation=f"Capitalised mid-heading: {', '.join(offenders)}",
            )

    @staticmethod
    def _to_sentence_case(words: list[str], allowed: set[str]) -> str:
        out = [words[0]]
        for word in words[1:]:
            out.append(word if word.strip(".,:;!?()[]") in allowed else word[:1].lower() + word[1:])
        return " ".join(out)


@register
class HeadingPunctuation(RuleBase):
    """Headings are labels, not sentences, so they do not end in a full stop."""

    rule_id: ClassVar[str] = "heading-punctuation"
    default_severity: ClassVar[Severity] = Severity.WARNING
    description: ClassVar[str] = "Flags trailing sentence punctuation on headings."

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        banned = str(options.get("characters", ".,;:"))
        for segment in document.segments:
            if segment.kind is not SegmentKind.HEADING:
                continue
            content = segment.content.rstrip()
            if not content or content[-1] not in banned:
                continue
            start = segment.start_offset + segment.content_offset
            yield self.finding(
                severity=self.default_severity,
                message=f"Heading ends with {content[-1]!r}; headings are labels, not sentences.",
                anchor=document.anchor(segment, start=start, end=start + len(segment.content)),
                original=segment.content,
                replacement=content.rstrip(banned),
            )


@register
class FenceLanguage(RuleBase):
    """Fenced code blocks declare a language, so they highlight and stay searchable."""

    rule_id: ClassVar[str] = "fence-language"
    default_severity: ClassVar[Severity] = Severity.WARNING
    description: ClassVar[str] = "Requires a language on fenced code blocks."

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        for segment in document.segments:
            if segment.kind is not SegmentKind.CODE or segment.info:
                continue
            if not segment.raw.lstrip().startswith(("```", "~~~")):
                continue  # an indented code block has nowhere to put a language
            # No replacement offered: the rule can tell the language is missing but cannot know
            # which one it should be. Reporting without guessing is the honest option.
            yield self.finding(
                severity=self.default_severity,
                message="Fenced code block has no language (for example ```bash).",
                anchor=document.anchor(segment),
            )


@register
class LongSentence(RuleBase):
    """Very long sentences, flagged but never rewritten."""

    rule_id: ClassVar[str] = "long-sentence"
    default_severity: ClassVar[Severity] = Severity.INFO
    description: ClassVar[str] = "Flags sentences longer than a configurable word count."

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        try:
            limit = int(options.get("max_words", 35))
        except (TypeError, ValueError):
            limit = 35
        if limit <= 0:
            return

        for segment in document.prose_segments:
            if segment.kind is SegmentKind.HEADING:
                continue
            for start, end, sentence in _sentences(segment.raw):
                words = [w for w in re.split(r"\s+", sentence.strip()) if w]
                if len(words) <= limit:
                    continue
                yield self.finding(
                    severity=self.default_severity,
                    message=f"Sentence runs to {len(words)} words (limit {limit}).",
                    anchor=document.anchor(
                        segment,
                        start=segment.start_offset + start,
                        end=segment.start_offset + end,
                    ),
                    original=sentence.strip(),
                )


@register
class PassiveVoice(RuleBase):
    """A heuristic for passive constructions. Reports, never rewrites."""

    rule_id: ClassVar[str] = "passive-voice"
    default_severity: ClassVar[Severity] = Severity.INFO
    description: ClassVar[str] = "Heuristically flags passive voice for a human to judge."

    PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+(?:ed|en))\b", re.IGNORECASE
    )
    # Common false friends: adjectives that end -ed and follow "is/are" innocently.
    ALLOW: ClassVar[frozenset[str]] = frozenset(
        {"based", "called", "named", "located", "related", "needed", "required", "used", "left"}
    )

    def check(self, document: Document, options: dict[str, Any]) -> Iterable[Finding]:
        allow = self.ALLOW | {
            str(w).lower() for w in options.get("allow", []) if isinstance(w, str)
        }
        for segment in document.prose_segments:
            if segment.kind is SegmentKind.HEADING:
                continue
            for match in self.PATTERN.finditer(segment.raw):
                if match.group(1).lower() in allow:
                    continue
                # No replacement: turning passive into active needs an actor the text may not
                # name. This rule surfaces candidates for a human, and says so.
                yield self.finding(
                    severity=self.default_severity,
                    message=f"Possible passive voice: {match.group(0)!r}.",
                    anchor=document.anchor(
                        segment,
                        start=segment.start_offset + match.start(),
                        end=segment.start_offset + match.end(),
                    ),
                    original=match.group(0),
                    explanation="Heuristic; rewrite only if it genuinely reads better.",
                )


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> Iterable[tuple[int, int, str]]:
    """Split into sentences, yielding `(start, end, text)` offsets within `text`."""
    position = 0
    for piece in _SENTENCE_END.split(text):
        if not piece:
            continue
        start = text.find(piece, position)
        if start < 0:
            start = position
        end = start + len(piece)
        position = end
        yield start, end, piece
