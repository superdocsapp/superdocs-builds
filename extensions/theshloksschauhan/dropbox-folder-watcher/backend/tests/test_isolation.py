"""Client folder isolation and Dropbox path scoping."""
from app.services.isolation import path_is_under, normalize_dropbox_path


def test_normalize_adds_slash_and_strips_trailing():
    assert normalize_dropbox_path("Clients/Acme/") == "/Clients/Acme"


def test_path_under_root():
    assert path_is_under("/Clients/Acme/Inbox/a.docx", "/Clients/Acme")
    assert path_is_under("/Clients/Acme", "/Clients/Acme")
    assert not path_is_under("/Clients/AcmeEvil/Inbox/a.docx", "/Clients/Acme")
    assert not path_is_under("/Clients/Beta/Inbox/a.docx", "/Clients/Acme")
