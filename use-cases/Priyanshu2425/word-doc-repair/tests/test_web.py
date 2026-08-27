"""The one conversation the page has with the server.

Narrow on purpose: these assert the payload carries what the page needs to show
a recovery — including the pictures — and that a refusal offers nothing it
cannot back up. The visual layer is tested in `frontend/`.
"""

from __future__ import annotations

import io
import json

import pytest
from starlette.testclient import TestClient

from tests import fixtures

from docrepair.web import app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def _recover(client: TestClient, blob: bytes, name: str = "site.docx") -> dict:
    res = client.post("/api/recover", files={"file": (name, io.BytesIO(blob))})
    assert res.status_code == 200
    last = [line for line in res.text.splitlines() if line.startswith("data: ")][-1]
    return json.loads(last[len("data: "):])


def test_the_payload_carries_the_pictures_it_recovered(client):
    payload = _recover(client, fixtures.illustrated())

    assert payload["ok"] is True
    assert payload["images_recovered"] == 1
    assert payload["images_lost"] == []


def test_the_payload_carries_the_document_itself(client):
    """A verdict is a claim; the preview is the thing the claim is about — and
    the pictures are what somebody is checking the preview for."""
    payload = _recover(client, fixtures.illustrated())

    assert 'src="data:image/png;base64,' in payload["preview_html"]


def test_the_downloaded_file_is_the_one_with_the_picture_in_it(client):
    payload = _recover(client, fixtures.illustrated())

    got = client.get(payload["download"])

    assert got.status_code == 200
    assert fixtures.media_names(got.content) == ["word/media/image1.png"]


def test_a_file_that_cannot_be_read_offers_no_download(client):
    payload = _recover(client, b"this is not a word file", "junk.docx")

    assert payload["ok"] is False
    assert payload["verdict"] == "refused"
    assert payload["preview_html"] == ""
    assert payload["lost"]


def test_an_empty_upload_is_refused_before_any_work(client):
    res = client.post("/api/recover", files={"file": ("x.docx", io.BytesIO(b""))})

    assert res.status_code == 400


def test_a_stale_download_token_says_the_original_was_never_touched(client):
    res = client.get("/api/download/deadbeef")

    assert res.status_code == 404
    assert "your original was never changed" in res.json()["detail"]
