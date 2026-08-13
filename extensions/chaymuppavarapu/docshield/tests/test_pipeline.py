from src.document import Document
from src.pipeline import DocShieldPipeline
from src.superdocs_client import SuperDocsResponse


class FakeSuperDocsClient:
    """Fake client used to test the pipeline without an API key."""

    def __init__(self, returned_html: str):
        self.returned_html = returned_html
        self.received_html = None
        self.received_instruction = None

    def edit(self, html: str, instruction: str) -> SuperDocsResponse:
        self.received_html = html
        self.received_instruction = instruction

        return SuperDocsResponse(
            html=self.returned_html,
            raw={"html": self.returned_html},
        )


def test_pipeline_accepts_content_only_edit():
    original = Document.from_html(
        """
        <article>
            <h1>John Doe</h1>
            <p>Software Engineer</p>
        </article>
        """
    )

    edited_html = """
    <article>
        <h1>Jane Doe</h1>
        <p>AI Engineer</p>
    </article>
    """

    client = FakeSuperDocsClient(edited_html)
    result = DocShieldPipeline(client).edit(
        original,
        "Improve the resume wording.",
    )

    assert result.accepted is True
    assert result.edited is not None
    assert result.validation is not None
    assert result.validation.accepted is True


def test_pipeline_rejects_element_removal():
    original = Document.from_html(
        """
        <article>
            <h1>John Doe</h1>
            <p>Software Engineer</p>
            <p>Python developer</p>
        </article>
        """
    )

    corrupted_html = """
    <article>
        <h1>John Doe</h1>
        <p>Python developer</p>
    </article>
    """

    client = FakeSuperDocsClient(corrupted_html)
    result = DocShieldPipeline(client).edit(
        original,
        "Improve the resume.",
    )

    assert result.accepted is False
    assert result.edited is None
    assert result.validation is not None

    assert any(
        issue.category == "element_count"
        for issue in result.validation.issues
    )


def test_pipeline_rejects_element_type_change():
    original = Document.from_html(
        """
        <article>
            <h1>John Doe</h1>
            <p>Software Engineer</p>
        </article>
        """
    )

    corrupted_html = """
    <article>
        <h1>John Doe</h1>
        <h1>Software Engineer</h1>
    </article>
    """

    client = FakeSuperDocsClient(corrupted_html)
    result = DocShieldPipeline(client).edit(
        original,
        "Improve the resume.",
    )

    assert result.accepted is False
    assert result.edited is None

    assert any(
        issue.category == "element_type"
        for issue in result.validation.issues
    )


def test_pipeline_rejects_image_source_change():
    original = Document.from_html(
        """
        <article>
            <h1>John Doe</h1>
            <img src="profile.png" alt="Profile photo">
        </article>
        """
    )

    corrupted_html = """
    <article>
        <h1>John Doe</h1>
        <img src="different.png" alt="Profile photo">
    </article>
    """

    client = FakeSuperDocsClient(corrupted_html)
    result = DocShieldPipeline(client).edit(
        original,
        "Improve the document.",
    )

    assert result.accepted is False

    assert any(
        issue.category == "attributes"
        for issue in result.validation.issues
    )


def test_pipeline_rejects_table_structure_change():
    original = Document.from_html(
        """
        <article>
            <h1>Resume</h1>
            <table>
                <tr>
                    <td>Skill</td>
                    <td>Level</td>
                </tr>
                <tr>
                    <td>Python</td>
                    <td>Advanced</td>
                </tr>
            </table>
        </article>
        """
    )

    corrupted_html = """
    <article>
        <h1>Resume</h1>
        <table>
            <tr>
                <td>Skill</td>
            </tr>
            <tr>
                <td>Python</td>
            </tr>
        </table>
    </article>
    """

    client = FakeSuperDocsClient(corrupted_html)
    result = DocShieldPipeline(client).edit(
        original,
        "Improve the table.",
    )

    assert result.accepted is False

    assert any(
        issue.category == "formatting"
        for issue in result.validation.issues
    )


def test_pipeline_passes_instruction_to_superdocs():
    original = Document.from_html(
        "<article><h1>John Doe</h1></article>"
    )

    client = FakeSuperDocsClient(
        "<article><h1>Jane Doe</h1></article>"
    )

    instruction = "Rewrite the heading."

    result = DocShieldPipeline(client).edit(
        original,
        instruction,
    )

    assert result.accepted is True
    assert client.received_instruction == instruction


def test_pipeline_sends_document_to_superdocs():
    original = Document.from_html(
        """
        <article>
            <h1>John Doe</h1>
            <p>Software Engineer</p>
        </article>
        """
    )

    client = FakeSuperDocsClient(
        """
        <article>
            <h1>Jane Doe</h1>
            <p>AI Engineer</p>
        </article>
        """
    )

    result = DocShieldPipeline(client).edit(
        original,
        "Rewrite the resume.",
    )

    assert result.accepted is True
    assert client.received_html is not None
    assert "<article>" in client.received_html
    assert "John Doe" in client.received_html


def test_pipeline_rejects_api_failure():
    class FailingClient:
        def edit(self, html: str, instruction: str):
            raise RuntimeError("SuperDocs API failed")

    original = Document.from_html(
        "<article><h1>John Doe</h1></article>"
    )

    result = DocShieldPipeline(
        FailingClient()
    ).edit(
        original,
        "Rewrite the heading.",
    )

    assert result.accepted is False
    assert result.edited is None
    assert result.error is not None
    assert "SuperDocs API failed" in result.error


def test_pipeline_rejects_unsupported_format():
    original = Document(
        source_format="latex",
        elements=[],
    )

    client = FakeSuperDocsClient(
        "<article><p>Hello</p></article>"
    )

    result = DocShieldPipeline(client).edit(
        original,
        "Rewrite this document.",
    )

    assert result.accepted is False
    assert result.edited is None
    assert result.error is not None
    assert "HTML" in result.error
