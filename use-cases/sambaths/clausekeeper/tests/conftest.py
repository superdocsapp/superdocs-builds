import sys
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT))

from clausekeeper import db, ingest, linking  # noqa: E402
from clausekeeper.cli import sync_clauses  # noqa: E402
from clausekeeper.library import LIBRARY_PATH, load_library, subset  # noqa: E402
from clausekeeper.superdocs import FixtureTransport, SuperDocsClient  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CORPUS = PROJECT / "corpus" / "northgate"


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    yield c
    c.close()


def client_for(script: str, **kw) -> SuperDocsClient:
    return SuperDocsClient(FixtureTransport(FIXTURES / script), **kw)


def seeded(conn, sample=None):
    client = client_for("init_link.json")
    ingest.init_session(client, conn, str(CORPUS))
    sync_clauses(conn, load_library(LIBRARY_PATH))
    clauses = subset(load_library(LIBRARY_PATH), sample)
    linking.build_links(client, conn, clauses)
    conn.execute(
        "INSERT OR IGNORE INTO our_jobs(job_id, purpose, created_at)"
        " VALUES('job_edit_01', 'guided-edit:NM-PRO-04',"
        " '2026-08-22T14:01:00Z')")
    conn.commit()
    return client


@pytest.fixture
def seeded_conn(conn):
    seeded(conn)
    return conn
