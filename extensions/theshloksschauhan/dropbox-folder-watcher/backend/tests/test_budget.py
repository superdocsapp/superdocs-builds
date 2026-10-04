"""Hourly operation budget is a hard stopping rule."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models.client import Client
from app.models.folder_config import FolderConfig
from app.models.job import Job, JobStatus
from app.services.budget import budget_allows_processing, billable_jobs_in_last_hour


def _folder(db, budget=1):
    client = Client(id=uuid.uuid4(), name="Acme", dropbox_folder_root="/Clients/Acme")
    db.add(client)
    db.flush()
    folder = FolderConfig(
        id=uuid.uuid4(),
        client_id=client.id,
        dropbox_folder_path="/Clients/Acme/Inbox",
        treatment="normalize",
        operation_budget_per_hour=budget,
        preview_mode=False,
    )
    db.add(folder)
    db.flush()
    return client, folder


def test_budget_blocks_after_limit(db_session):
    client, folder = _folder(db_session, budget=1)
    job = Job(
        id=uuid.uuid4(),
        client_id=client.id,
        folder_config_id=folder.id,
        source_path="/Clients/Acme/Inbox/a.docx",
        source_rev="rev1",
        status=JobStatus.REVIEW_PENDING,
        preview=False,
        updated_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    db_session.commit()

    assert billable_jobs_in_last_hour(db_session, folder.id) == 1
    assert budget_allows_processing(db_session, folder) is False


def test_preview_folder_ignores_budget(db_session):
    _, folder = _folder(db_session, budget=0)
    folder.preview_mode = True
    db_session.commit()
    assert budget_allows_processing(db_session, folder) is True


def test_old_jobs_do_not_count(db_session):
    client, folder = _folder(db_session, budget=1)
    job = Job(
        id=uuid.uuid4(),
        client_id=client.id,
        folder_config_id=folder.id,
        source_path="/Clients/Acme/Inbox/old.docx",
        source_rev="rev-old",
        status=JobStatus.COMPLETED,
        preview=False,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db_session.add(job)
    db_session.commit()
    assert budget_allows_processing(db_session, folder) is True
