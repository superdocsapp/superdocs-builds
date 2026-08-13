from src.document import Document
from src.validator import validate_document


def test_text_changes_are_allowed():
    before = Document.from_html(
        "<article><h1>Old heading</h1><p>Hello world</p></article>"
    )

    after = Document.from_html(
        "<article><h1>New heading</h1><p>Hola mundo</p></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is True
    assert result.issue_count == 0


def test_element_type_change_is_rejected():
    before = Document.from_html(
        "<article><p>Hello</p></article>"
    )

    after = Document.from_html(
        "<article><h1>Hello</h1></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "element_type"
        for issue in result.issues
    )


def test_element_removal_is_rejected():
    before = Document.from_html(
        "<article><h1>Title</h1><p>Hello</p></article>"
    )

    after = Document.from_html(
        "<article><h1>Title</h1></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "element_removed"
        for issue in result.issues
    )


def test_element_addition_is_rejected():
    before = Document.from_html(
        "<article><h1>Title</h1></article>"
    )

    after = Document.from_html(
        "<article><h1>Title</h1><p>Hello</p></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "element_added"
        for issue in result.issues
    )


def test_image_attribute_change_is_rejected():
    before = Document.from_html(
        '<article><img src="resume.png" alt="Resume"/></article>'
    )

    after = Document.from_html(
        '<article><img src="other.png" alt="Resume"/></article>'
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "attributes"
        for issue in result.issues
    )


def test_table_structure_change_is_rejected():
    before = Document.from_html(
        """
        <article>
            <table>
                <tr><td>A</td><td>B</td></tr>
            </table>
        </article>
        """
    )

    after = Document.from_html(
        """
        <article>
            <table>
                <tr><td>A</td></tr>
            </table>
        </article>
        """
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "formatting"
        for issue in result.issues
    )


def test_heading_level_change_is_rejected():
    before = Document.from_html(
        "<article><h1>Title</h1></article>"
    )

    after = Document.from_html(
        "<article><h2>Title</h2></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "element_type"
        for issue in result.issues
    )
def test_unchanged_document_is_accepted():
    html = """
    <article>
        <h1>Resume</h1>
        <p>Software Engineer</p>
    </article>
    """

    before = Document.from_html(html)
    after = Document.from_html(html)

    result = validate_document(before, after)

    assert result.accepted is True
    assert result.issue_count == 0


def test_formatting_change_is_rejected():
    before = Document.from_html(
        "<article><h1>Resume</h1></article>"
    )

    after = Document.from_html(
        "<article><h2>Resume</h2></article>"
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "element_type"
        for issue in result.issues
    )


def test_source_format_change_is_rejected():
    before = Document(
        source_format="html",
        elements=[],
    )

    after = Document(
        source_format="markdown",
        elements=[],
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert any(
        issue.category == "source_format"
        for issue in result.issues
    )


def test_multiple_structural_changes_are_reported():
    before = Document.from_html(
        """
        <article>
            <h1>Resume</h1>
            <p>Experience</p>
            <img src="resume.png" alt="Resume"/>
        </article>
        """
    )

    after = Document.from_html(
        """
        <article>
            <h2>Resume</h2>
            <img src="other.png" alt="Different"/>
        </article>
        """
    )

    result = validate_document(before, after)

    assert result.accepted is False
    assert result.issue_count >= 2
