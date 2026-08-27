import os

import psycopg
import pytest

from scripts.migrate import migrate


@pytest.fixture(autouse=True)
def clean_integration_database() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if database_url is None:
        yield
        return

    os.environ["DATABASE_URL"] = database_url
    os.environ.setdefault("MANAGEMENT_TOKEN", "m" * 32)
    os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "g" * 32)
    from app.config import get_settings

    get_settings.cache_clear()
    migrate()
    with psycopg.connect(database_url) as connection:
        connection.execute("TRUNCATE TABLE deliveries CASCADE")

    yield
    get_settings.cache_clear()
