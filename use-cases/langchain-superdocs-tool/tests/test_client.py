"""
Unit and integration tests for SuperDocsClient.
"""

from superdocs_langchain.client import SuperDocsClient
from superdocs_langchain.models import ExportFormat, SectionEditMode


def test_create_and_get_document(client: SuperDocsClient):
    res = client.create_document(
        title="Sprint Retrospective",
        content="# Overview\nSprint went well.\n\n## Action Items\nImprove CI speed.",
        folder="agile",
        metadata={"sprint": 42},
    )
    assert res.success is True
    assert "data" in res.model_dump()
    doc_id = res.data["id"]

    # Retrieve full document
    get_res = client.get_document(doc_id)
    assert get_res.success is True
    assert get_res.data["title"] == "Sprint Retrospective"
    assert len(get_res.data["sections"]) >= 2

    # Retrieve outline
    outline_res = client.get_document(doc_id, include_outline=True)
    assert outline_res.success is True
    assert "outline" in outline_res.data
    assert len(outline_res.data["outline"]) >= 2


def test_get_document_not_found(client: SuperDocsClient):
    res = client.get_document("non_existent_doc_id")
    assert res.success is False
    assert res.error == "NotFound"


def test_edit_section_replace(client: SuperDocsClient):
    create_res = client.create_document(
        title="API Spec",
        content="## Endpoints\nGET /users\n\n## Authentication\nBasic Auth",
    )
    doc_id = create_res.data["id"]

    # Replace Authentication section
    edit_res = client.edit_section(
        document_id=doc_id,
        section_target="Authentication",
        content="OAuth2 Bearer Tokens (JWT)",
        mode=SectionEditMode.REPLACE,
    )
    assert edit_res.success is True
    assert "OAuth2 Bearer Tokens (JWT)" in edit_res.data["content"]
    assert "Basic Auth" not in edit_res.data["content"]
    assert edit_res.data["version"] == 2


def test_edit_section_append_prepend_delete(client: SuperDocsClient):
    create_res = client.create_document(
        title="Runbook",
        content="## Step 1\nInitialize node.\n\n## Step 2\nRun migrations.",
    )
    doc_id = create_res.data["id"]

    # Prepend
    client.edit_section(
        document_id=doc_id,
        section_target="Step 1",
        content="Check prerequisites.",
        mode=SectionEditMode.PREPEND,
    )
    doc = client.get_document(doc_id).data
    assert "Check prerequisites.\n\nInitialize node." in doc["content"]

    # Append
    client.edit_section(
        document_id=doc_id,
        section_target="Step 2",
        content="Verify database health.",
        mode=SectionEditMode.APPEND,
    )
    doc = client.get_document(doc_id).data
    assert "Run migrations.\n\nVerify database health." in doc["content"]

    # Delete
    del_res = client.edit_section(
        document_id=doc_id,
        section_target="Step 1",
        content="",
        mode=SectionEditMode.DELETE,
    )
    assert del_res.success is True
    doc_after = client.get_document(doc_id).data
    assert "Step 1" not in doc_after["content"]


def test_search_documents(populated_client: SuperDocsClient):
    # Query matching microservices content
    res = populated_client.search(query="Envoy routing", top_k=5)
    assert res.success is True
    results = res.data["results"]
    assert len(results) > 0
    assert any("Microservices" in r["title"] for r in results)

    # Query with tag filter
    tagged_res = populated_client.search(query="scaling", tag_filter="database")
    assert tagged_res.success is True
    assert any("Database Sharding" in r["title"] for r in tagged_res.data["results"])


def test_render_template(client: SuperDocsClient):
    res = client.render_template(
        template_id="tech-spec",
        variables={
            "project_name": "Agentic Pipeline",
            "summary": "High throughput agent data engine",
            "architecture": "Event driven actor model",
            "api_specs": "gRPC + GraphQL",
            "security": "mTLS encryption",
        },
        target_title="Agnetic Architecture Spec",
    )
    assert res.success is True
    doc_id = res.data["id"]
    assert res.data["title"] == "Agnetic Architecture Spec"
    assert "Agentic Pipeline" in res.data["content"]
    assert "Event driven actor model" in res.data["content"]


def test_export_document_formats(client: SuperDocsClient):
    create_res = client.create_document(
        title="Export Test Doc",
        content="# Header 1\nSome **bold** markdown content.\n\n## Subheader\nMore content.",
    )
    doc_id = create_res.data["id"]

    # Markdown export
    md_res = client.export_document(doc_id, ExportFormat.MARKDOWN)
    assert md_res.success is True
    assert "Some **bold** markdown content." in md_res.data["content"]

    # HTML export
    html_res = client.export_document(doc_id, ExportFormat.HTML)
    assert html_res.success is True
    assert "<html>" in html_res.data["content"]
    assert "<h1>Export Test Doc</h1>" in html_res.data["content"]

    # Text export
    txt_res = client.export_document(doc_id, ExportFormat.TEXT)
    assert txt_res.success is True
    assert "**" not in txt_res.data["content"]

    # JSON export
    json_res = client.export_document(doc_id, ExportFormat.JSON)
    assert json_res.success is True
    assert '"title": "Export Test Doc"' in json_res.data["content"]


def test_comments_and_history(client: SuperDocsClient):
    create_res = client.create_document(
        title="Comment & History Test",
        content="## Section 1\nInitial text.",
    )
    doc_id = create_res.data["id"]

    # Add comment
    c_res = client.add_comment(
        document_id=doc_id,
        content="Needs more citations.",
        author="code-reviewer",
    )
    assert c_res.success is True

    # Retrieve comments
    get_c = client.get_comments(doc_id)
    assert get_c.success is True
    assert len(get_c.data["comments"]) == 1
    assert get_c.data["comments"][0]["author"] == "code-reviewer"

    # Edit to generate version
    client.edit_section(doc_id, "Section 1", "Updated version 2 text.")
    history_res = client.get_history(doc_id)
    assert history_res.success is True
    assert len(history_res.data["versions"]) >= 2

    # Revert to v1
    revert_res = client.revert_version(doc_id, "v1")
    assert revert_res.success is True
    doc_reverted = client.get_document(doc_id).data
    assert "Initial text." in doc_reverted["content"]
