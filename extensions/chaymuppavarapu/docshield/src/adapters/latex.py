from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..document import Document, DocumentElement


# Commands that are important to document fidelity.
STRUCTURAL_COMMANDS = {
    "documentclass",
    "usepackage",
    "RequirePackage",
    "geometry",
    "setlength",
    "addtolength",
    "newcommand",
    "renewcommand",
    "providecommand",
    "def",
    "title",
    "author",
    "date",
    "hypersetup",
}


# Environments whose structure should be protected.
STRUCTURAL_ENVIRONMENTS = {
    "document",
    "itemize",
    "enumerate",
    "description",
    "tabular",
    "tabularx",
    "longtable",
    "table",
    "figure",
    "center",
    "flushleft",
    "flushright",
    "minipage",
    "equation",
    "align",
    "align*",
}


_COMMAND_RE = re.compile(
    r"\\([A-Za-z@]+)(?:\s*\*?)"
    r"(?:\s*\[[^\]]*\])?"
    r"(?:\s*\{([^{}]*)\})?"
)


_ENV_RE = re.compile(
    r"\\(begin|end)\s*\{([^}]+)\}"
)


def _strip_comments(source: str) -> str:
    """
    Remove LaTeX comments while preserving escaped percent signs.

    A percent sign preceded by an odd number of backslashes is treated
    as escaped and is therefore preserved.
    """

    lines: list[str] = []

    for line in source.splitlines():
        result: list[str] = []
        escaped = False

        for character in line:
            if character == "%" and not escaped:
                break

            result.append(character)

            if character == "\\":
                escaped = not escaped
            else:
                escaped = False

        lines.append("".join(result))

    return "\n".join(lines)


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_commands(source: str) -> list[dict[str, Any]]:
    """
    Extract commands relevant to document structure and formatting.
    """

    commands: list[dict[str, Any]] = []

    for match in _COMMAND_RE.finditer(source):
        name = match.group(1)

        if name not in STRUCTURAL_COMMANDS:
            continue

        argument = match.group(2)

        commands.append(
            {
                "name": name,
                "argument": _normalize_whitespace(argument or ""),
            }
        )

    return commands


def _extract_environments(source: str) -> list[dict[str, Any]]:
    """
    Extract begin/end environment markers in source order.
    """

    environments: list[dict[str, Any]] = []

    for match in _ENV_RE.finditer(source):
        action = match.group(1)
        name = match.group(2).strip()

        environments.append(
            {
                "action": action,
                "name": name,
                "protected": name in STRUCTURAL_ENVIRONMENTS,
            }
        )

    return environments


def _extract_sections(source: str) -> list[dict[str, Any]]:
    """
    Extract section hierarchy without modifying the source.
    """

    pattern = re.compile(
        r"\\(part|chapter|section|subsection|subsubsection)"
        r"\*?\s*\{([^{}]*)\}"
    )

    sections: list[dict[str, Any]] = []

    levels = {
        "part": 0,
        "chapter": 1,
        "section": 2,
        "subsection": 3,
        "subsubsection": 4,
    }

    for index, match in enumerate(pattern.finditer(source)):
        command = match.group(1)
        title = _normalize_whitespace(match.group(2))

        sections.append(
            {
                "index": index,
                "command": command,
                "level": levels[command],
                "title": title,
            }
        )

    return sections


def _extract_images(source: str) -> list[dict[str, str]]:
    """
    Extract \\includegraphics references.

    The image path is structural information and must not silently
    disappear during an edit.
    """

    pattern = re.compile(
        r"\\includegraphics"
        r"(?:\s*\[[^\]]*\])?"
        r"\s*\{([^}]+)\}"
    )

    return [
        {
            "path": _normalize_whitespace(match.group(1)),
        }
        for match in pattern.finditer(source)
    ]


def _extract_links(source: str) -> list[dict[str, str]]:
    """
    Extract common hyperlink targets.
    """

    links: list[dict[str, str]] = []

    href_pattern = re.compile(
        r"\\href\s*\{([^}]+)\}\s*\{([^{}]*)\}"
    )

    for match in href_pattern.finditer(source):
        links.append(
            {
                "target": _normalize_whitespace(match.group(1)),
                "text": _normalize_whitespace(match.group(2)),
            }
        )

    url_pattern = re.compile(
        r"\\url\s*\{([^}]+)\}"
    )

    for match in url_pattern.finditer(source):
        links.append(
            {
                "target": _normalize_whitespace(match.group(1)),
                "text": "",
            }
        )

    return links


def _extract_lists(source: str) -> list[dict[str, Any]]:
    """
    Capture list environments and their item counts.
    """

    lists: list[dict[str, Any]] = []

    for environment in ("itemize", "enumerate", "description"):
        pattern = re.compile(
            rf"\\begin\s*\{{{re.escape(environment)}\}}"
            rf"(.*?)"
            rf"\\end\s*\{{{re.escape(environment)}\}}",
            re.DOTALL,
        )

        for index, match in enumerate(pattern.finditer(source)):
            body = match.group(1)

            lists.append(
                {
                    "type": environment,
                    "index": index,
                    "item_count": len(
                        re.findall(r"\\item(?:\s|\[|\Z)", body)
                    ),
                }
            )

    return lists


def parse_latex(source: str) -> Document:
    """
    Parse LaTeX into DocShield's normalized document representation.

    The original source is preserved verbatim in Document.metadata.
    The normalized elements represent structural invariants that can be
    compared before and after a SuperDocs edit.
    """

    if not isinstance(source, str):
        raise TypeError("LaTeX source must be a string.")

    if not source.strip():
        raise ValueError("LaTeX source cannot be empty.")

    clean_source = _strip_comments(source)

    elements: list[DocumentElement] = []
    counters: dict[str, int] = {}

    def add_element(
        element_type: str,
        text: str = "",
        attributes: dict[str, str] | None = None,
        formatting: dict[str, Any] | None = None,
    ) -> None:
        index = counters.get(element_type, 0)
        counters[element_type] = index + 1

        elements.append(
            DocumentElement(
                element_type=element_type,
                index=index,
                text=_normalize_whitespace(text),
                attributes=attributes or {},
                formatting=formatting or {},
            )
        )

    commands = _extract_commands(clean_source)

    for command in commands:
        add_element(
            "command",
            text=command["argument"],
            attributes={
                "name": command["name"],
            },
            formatting={
                "protected": True,
            },
        )

    sections = _extract_sections(clean_source)

    for section in sections:
        add_element(
            "section",
            text=section["title"],
            attributes={
                "command": section["command"],
            },
            formatting={
                "level": section["level"],
            },
        )

    environments = _extract_environments(clean_source)

    for environment in environments:
        add_element(
            "environment",
            attributes={
                "name": environment["name"],
                "action": environment["action"],
            },
            formatting={
                "protected": environment["protected"],
            },
        )

    for image in _extract_images(clean_source):
        add_element(
            "image",
            attributes={
                "path": image["path"],
            },
            formatting={
                "protected": True,
            },
        )

    for link in _extract_links(clean_source):
        add_element(
            "link",
            text=link["text"],
            attributes={
                "target": link["target"],
            },
            formatting={
                "protected": True,
            },
        )

    for item_list in _extract_lists(clean_source):
        add_element(
            "list",
            attributes={
                "type": item_list["type"],
            },
            formatting={
                "item_count": item_list["item_count"],
                "protected": True,
            },
        )

    return Document(
        source_format="latex",
        elements=elements,
        metadata={
            "original_source": source,
            "normalized_source": clean_source,
            "command_count": len(commands),
            "section_count": len(sections),
            "environment_count": len(environments),
            "image_count": len(_extract_images(clean_source)),
            "link_count": len(_extract_links(clean_source)),
        },
        raw_content=source,
    )


def load_latex(path: str | Path) -> Document:
    """
    Load a LaTeX source file.
    """

    file_path = Path(path)

    if not file_path.exists():
        raise FileNotFoundError(file_path)

    if file_path.suffix.lower() not in {".tex", ".latex"}:
        raise ValueError(
            f"Unsupported LaTeX extension: {file_path.suffix}"
        )

    return parse_latex(
        file_path.read_text(
            encoding="utf-8"
        )
    )