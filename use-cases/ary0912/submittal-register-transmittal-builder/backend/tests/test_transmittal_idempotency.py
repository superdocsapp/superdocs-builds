import asyncio
import base64
import importlib
import sys
import types

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class CountingSuperDocsClient:
    def __init__(self):
        self.upload_count = 0
        self.export_count = 0

    async def upload_document(self, filename, content):
        self.upload_count += 1
        return {
            "session_id": "session-1",
            "document_html": content.decode("utf-8"),
        }

    async def export_document(
        self,
        session_id,
        format="docx",
        html=None,
        filename=None,
    ):
        self.export_count += 1
        return {
            "session_id": session_id,
            "format": format,
            "filename": filename,
            "content_base64": base64.b64encode(
                b"PK\\x03\\x04test-docx"
            ).decode("ascii"),
        }


@pytest.fixture
def transmittal_context(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)

    # Importing app.main normally initializes the PostgreSQL LangGraph
    # checkpointer. Replace only that runtime module for this isolated test.
    runtime = types.ModuleType("app.agents.runtime")
    runtime.workflow = object()
    monkeypatch.setitem(sys.modules, "app.agents.runtime", runtime)

    main = importlib.import_module("app.main")
    db_module = importlib.import_module("app.db.session")
    models = importlib.import_module("app.models")

    engine = create_engine(database_url)
    db_module.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    client = CountingSuperDocsClient()
    monkeypatch.setattr(main, "get_superdocs_client", lambda: client)
    monkeypatch.setattr(main, "EXPORTS_DIR", tmp_path / "exports")

    yield main, db, models, client

    db.close()
    engine.dispose()


def _seed_reviewed_submittal(models, db):
    submittal = models.Submittal(
        project_id="BROD-2026",
        number="SUB-001",
        title="Flooring",
        specification_section="09 65 00",
    )
    db.add(submittal)
    db.flush()
    db.add(
        models.Finding(
            submittal_id=submittal.id,
            attribute="Thickness",
            requirement="3 mm",
            submitted_value="3 mm",
            result="PASS",
            specification_evidence="Spec",
            submission_evidence="Submittal",
            status="APPROVED",
            reviewer="Reviewer",
        )
    )
    db.commit()
    return submittal


def test_repeated_creation_reuses_transmittal_and_session(
    transmittal_context,
):
    main, db, models, client = transmittal_context
    _seed_reviewed_submittal(models, db)

    first = asyncio.run(main.create_transmittal("SUB-001", db))
    second = asyncio.run(main.create_transmittal("SUB-001", db))

    assert first["transmittal_id"] == second["transmittal_id"]
    assert first["session_id"] == second["session_id"]
    assert client.upload_count == 1
    assert db.query(models.Transmittal).count() == 1


def test_exported_transmittal_is_reused_and_cannot_be_edited(
    transmittal_context,
):
    main, db, models, client = transmittal_context
    submittal = _seed_reviewed_submittal(models, db)
    exported = models.Transmittal(
        project_id=submittal.project_id,
        submittal_id=submittal.id,
        number="TR-SUB-001",
        status="EXPORTED",
        superdocs_session_id="session-exported",
        export_url="mock://transmittal.docx",
    )
    db.add(exported)
    db.commit()

    response = asyncio.run(main.create_transmittal("SUB-001", db))

    assert response["transmittal_id"] == exported.id
    assert response["session_id"] == "session-exported"
    assert response["export_url"] == "mock://transmittal.docx"
    assert client.upload_count == 0

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.edit_transmittal(exported.id, "change", db))
    assert error.value.status_code == 409
    assert "cannot be edited" in error.value.detail


def test_export_persists_docx_and_downloads_without_superdocs(
    transmittal_context,
):
    main, db, models, client = transmittal_context
    submittal = _seed_reviewed_submittal(models, db)
    transmittal = models.Transmittal(
        project_id=submittal.project_id,
        submittal_id=submittal.id,
        number="TR-SUB-001",
        status="EDIT_APPROVED",
        superdocs_session_id="session-approved",
    )
    db.add(transmittal)
    db.commit()

    response = asyncio.run(
        main.export_transmittal(transmittal.id, db)
    )
    export_path = main.EXPORTS_DIR / "TR-SUB-001.docx"

    assert response["status"] == "EXPORTED"
    assert export_path.is_file()
    assert export_path.stat().st_size > 0
    assert transmittal.export_url == (
        f"/transmittals/{transmittal.id}/download"
    )
    assert client.export_count == 1

    downloaded = asyncio.run(
        main.download_transmittal(transmittal.id, db)
    )
    assert downloaded.path == str(export_path)
    assert downloaded.media_type == (
        "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document"
    )
    assert downloaded.filename == "TR-SUB-001.docx"
    assert client.export_count == 1

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(main.export_transmittal(transmittal.id, db))
    assert error.value.status_code == 409
    assert client.export_count == 1


def test_download_returns_404_when_export_file_is_missing(
    transmittal_context,
):
    main, db, models, client = transmittal_context
    submittal = _seed_reviewed_submittal(models, db)
    transmittal = models.Transmittal(
        project_id=submittal.project_id,
        submittal_id=submittal.id,
        number="TR-SUB-001",
        status="EXPORTED",
        superdocs_session_id="session-exported",
    )
    db.add(transmittal)
    db.commit()

    with pytest.raises(main.HTTPException) as error:
        asyncio.run(
            main.download_transmittal(transmittal.id, db)
        )
    assert error.value.status_code == 404
    assert error.value.detail == "Exported document not found."
    assert client.export_count == 0
