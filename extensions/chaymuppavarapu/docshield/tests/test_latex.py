from src.adapters.latex import parse_latex, load_latex


def test_parse_basic_latex():
    source = r"""
\documentclass[11pt]{article}
\usepackage[margin=0.7in]{geometry}

\begin{document}

\section{Experience}

Built an AI application.

\end{document}
"""

    document = parse_latex(source)

    assert document.source_format == "latex"
    assert document.metadata["original_source"] == source
    assert document.metadata["command_count"] >= 2
    assert document.metadata["section_count"] == 1
    assert document.metadata["environment_count"] == 2


def test_documentclass_is_protected():
    source = r"""
\documentclass[11pt]{article}
\begin{document}
Hello
\end{document}
"""

    document = parse_latex(source)

    commands = [
        element
        for element in document.elements
        if element.element_type == "command"
    ]

    assert any(
        element.attributes.get("name") == "documentclass"
        for element in commands
    )


def test_packages_are_detected():
    source = r"""
\documentclass{article}
\usepackage{geometry}
\usepackage{hyperref}
\usepackage{xcolor}

\begin{document}
Hello
\end{document}
"""

    document = parse_latex(source)

    packages = [
        element.text
        for element in document.elements
        if element.element_type == "command"
        and element.attributes.get("name") == "usepackage"
    ]

    assert packages == [
        "geometry",
        "hyperref",
        "xcolor",
    ]


def test_section_hierarchy_is_detected():
    source = r"""
\begin{document}

\section{Experience}
\subsection{Software Engineer}
\subsubsection{Project}

\end{document}
"""

    document = parse_latex(source)

    sections = [
        element
        for element in document.elements
        if element.element_type == "section"
    ]

    assert len(sections) == 3

    assert sections[0].text == "Experience"
    assert sections[0].formatting["level"] == 2

    assert sections[1].text == "Software Engineer"
    assert sections[1].formatting["level"] == 3

    assert sections[2].text == "Project"
    assert sections[2].formatting["level"] == 4


def test_list_structure_is_detected():
    source = r"""
\begin{document}

\begin{itemize}
    \item First achievement
    \item Second achievement
    \item Third achievement
\end{itemize}

\end{document}
"""

    document = parse_latex(source)

    lists = [
        element
        for element in document.elements
        if element.element_type == "list"
    ]

    assert len(lists) == 1
    assert lists[0].attributes["type"] == "itemize"
    assert lists[0].formatting["item_count"] == 3


def test_images_are_detected():
    source = r"""
\begin{document}

\includegraphics[width=0.8\textwidth]{profile.png}

\end{document}
"""

    document = parse_latex(source)

    images = [
        element
        for element in document.elements
        if element.element_type == "image"
    ]

    assert len(images) == 1
    assert images[0].attributes["path"] == "profile.png"
    assert images[0].formatting["protected"] is True


def test_links_are_detected():
    source = r"""
\begin{document}

\href{https://github.com/example}{GitHub}
\url{https://example.com}

\end{document}
"""

    document = parse_latex(source)

    links = [
        element
        for element in document.elements
        if element.element_type == "link"
    ]

    assert len(links) == 2

    assert links[0].attributes["target"] == "https://github.com/example"
    assert links[0].text == "GitHub"

    assert links[1].attributes["target"] == "https://example.com"


def test_comments_are_not_treated_as_structure():
    source = r"""
\documentclass{article}

% \usepackage{fakepackage}
% \section{Fake Section}

\begin{document}
Real content
\end{document}
"""

    document = parse_latex(source)

    packages = [
        element
        for element in document.elements
        if element.element_type == "command"
        and element.attributes.get("name") == "usepackage"
    ]

    sections = [
        element
        for element in document.elements
        if element.element_type == "section"
    ]

    assert packages == []
    assert sections == []


def test_escaped_percent_is_preserved():
    source = r"""
\begin{document}

Achievement: 100\% improvement.

\end{document}
"""

    document = parse_latex(source)

    assert r"100\% improvement." in document.metadata["normalized_source"]


def test_empty_latex_is_rejected():
    try:
        parse_latex("")
    except ValueError:
        pass
    else:
        raise AssertionError("Empty LaTeX should be rejected")


def test_load_latex_file(tmp_path):
    path = tmp_path / "resume.tex"

    source = r"""
\documentclass{article}
\begin{document}
\section{Education}
University
\end{document}
"""

    path.write_text(source, encoding="utf-8")

    document = load_latex(path)

    assert document.source_format == "latex"
    assert document.metadata["original_source"] == source
    assert document.metadata["section_count"] == 1


def test_invalid_latex_extension_is_rejected(tmp_path):
    path = tmp_path / "resume.txt"
    path.write_text("Hello", encoding="utf-8")

    try:
        load_latex(path)
    except ValueError:
        pass
    else:
        raise AssertionError(
            "Non-LaTeX extensions should be rejected"
        )
from src.adapters.latex import parse_latex
from src.fingerprint import fingerprint, same_document, changed_elements


def test_identical_latex_has_same_fingerprint():
    source = r"""
\documentclass{article}
\usepackage{geometry}

\begin{document}
\section{Experience}
Built software.
\end{document}
"""

    first = fingerprint(parse_latex(source))
    second = fingerprint(parse_latex(source))

    assert same_document(first, second)


def test_package_removal_changes_fingerprint():
    before = r"""
\documentclass{article}
\usepackage{geometry}
\usepackage{hyperref}

\begin{document}
Hello
\end{document}
"""

    after = r"""
\documentclass{article}
\usepackage{geometry}

\begin{document}
Hello
\end{document}
"""

    first = fingerprint(parse_latex(before))
    second = fingerprint(parse_latex(after))

    assert not same_document(first, second)


def test_section_removal_changes_fingerprint():
    before = r"""
\begin{document}

\section{Experience}
\section{Education}

\end{document}
"""

    after = r"""
\begin{document}

\section{Experience}

\end{document}
"""

    first = fingerprint(parse_latex(before))
    second = fingerprint(parse_latex(after))

    assert not same_document(first, second)


def test_environment_change_changes_fingerprint():
    before = r"""
\begin{document}

\begin{itemize}
\item One
\item Two
\end{itemize}

\end{document}
"""

    after = r"""
\begin{document}

\begin{enumerate}
\item One
\item Two
\end{enumerate}

\end{document}
"""

    first = fingerprint(parse_latex(before))
    second = fingerprint(parse_latex(after))

    assert not same_document(first, second)


def test_image_removal_changes_fingerprint():
    before = r"""
\begin{document}

\includegraphics{profile.png}

\end{document}
"""

    after = r"""
\begin{document}

\end{document}
"""

    first = fingerprint(parse_latex(before))
    second = fingerprint(parse_latex(after))

    assert not same_document(first, second)


def test_fingerprint_explains_latex_change():
    before = r"""
\documentclass{article}
\usepackage{geometry}

\begin{document}
Hello
\end{document}
"""

    after = r"""
\documentclass{article}
\usepackage{geometry}
\usepackage{hyperref}

\begin{document}
Hello
\end{document}
"""

    first = fingerprint(parse_latex(before))
    second = fingerprint(parse_latex(after))

    changes = changed_elements(first, second)

    assert changes
    assert any(
        change["after"]
        and change["after"]["type"] == "command"
        for change in changes
    )
