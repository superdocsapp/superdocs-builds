"""
test_superdocs_client.py -- regression coverage for SuperDocsClient request
payload shapes, using a monkeypatched requests.Session.request so we never
hit the network. Added after a live 502 surfaced from the app:

    SuperDocs API error 422 on .../v1/documents/images/upload-base64:
    {'detail': [{'type': 'missing', 'loc': ['body', 'image_base64'],
    'msg': 'Field required', ...}]}

upload_image_base64 was sending the request body key "file_base64" (the key
used by the sibling /v1/documents/upload-base64 and /v1/templates/upload-base64
endpoints), but the images endpoint actually expects "image_base64". This
test locks in the correct field name so it can't silently regress again.
"""
import base64

import pytest

import main
from superdocs_client import SuperDocsClient, SuperDocsError


class _FakeResponse:
    def __init__(self, json_body):
        self.status_code = 200
        self._json_body = json_body
        self.content = b"{}"

    def json(self):
        return self._json_body


@pytest.fixture
def client():
    return SuperDocsClient(api_key="sk_test_dummy")


def test_upload_image_base64_sends_image_base64_field(client, monkeypatch):
    captured = {}

    def fake_request(method, url, timeout=None, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        return _FakeResponse({"url": "https://fake/images/x.jpg"})

    monkeypatch.setattr(client._session, "request", fake_request)

    image_bytes = b"\xff\xd8\xff\xe0fake-jpeg-bytes"
    client.upload_image_base64(filename="hero.jpg", image_bytes=image_bytes)

    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v1/documents/images/upload-base64")
    body = captured["json"]
    assert "image_base64" in body, "images/upload-base64 requires the 'image_base64' field, not 'file_base64'"
    assert "file_base64" not in body
    assert body["image_base64"] == base64.b64encode(image_bytes).decode("ascii")
    assert body["filename"] == "hero.jpg"


def test_upload_document_base64_still_uses_file_base64_field(client, monkeypatch):
    """Sanity check the sibling endpoint's field name wasn't accidentally changed too."""
    captured = {}

    def fake_request(method, url, timeout=None, **kwargs):
        captured["json"] = kwargs.get("json")
        return _FakeResponse({"document_id": "doc-1"})

    monkeypatch.setattr(client._session, "request", fake_request)

    client.upload_document_base64(filename="doc.html", html_or_bytes="<p>hi</p>", session_id="sess-1")

    body = captured["json"]
    assert "file_base64" in body
    assert "image_base64" not in body


# -------------------------------------------------------------------------- #
# _extract_image_url -- robust response-shape handling
# -------------------------------------------------------------------------- #
#
# The images/upload-base64 response schema is untyped ({}) in SuperDocs' own
# OpenAPI spec, so the key holding the URL isn't guaranteed the way the
# request body is. Guessing a single key name got us burned once already
# (see the request-body fix above); _extract_image_url() is deliberately
# defensive so a future shape change surfaces as a clear 502 instead of a
# silently empty <img src="">.


def test_extract_image_url_standard_key():
    assert main._extract_image_url({"url": "https://cdn.example/x.jpg"}) == "https://cdn.example/x.jpg"


def test_extract_image_url_alternate_keys():
    assert main._extract_image_url({"image_url": "https://cdn.example/a.jpg"}) == "https://cdn.example/a.jpg"
    assert main._extract_image_url({"file_url": "https://cdn.example/b.jpg"}) == "https://cdn.example/b.jpg"
    assert main._extract_image_url({"public_url": "https://cdn.example/c.jpg"}) == "https://cdn.example/c.jpg"


def test_extract_image_url_nested_dict():
    assert main._extract_image_url({"data": {"url": "https://cdn.example/nested.jpg"}}) == "https://cdn.example/nested.jpg"


def test_extract_image_url_scans_unknown_string_key_as_last_resort():
    assert main._extract_image_url({"totally_unexpected_key": "https://cdn.example/found-me.jpg"}) == "https://cdn.example/found-me.jpg"


def test_extract_image_url_raises_when_nothing_url_shaped():
    with pytest.raises(SuperDocsError):
        main._extract_image_url({"status": "ok", "id": "abc123"})


def test_extract_image_url_raises_on_non_dict():
    with pytest.raises(SuperDocsError):
        main._extract_image_url("not a dict")
