"""
test_v2_api.py -- end-to-end coverage of main.py's v2 endpoints against
FakeSuperDocsClient + in-memory SQLite (see conftest.py). Exercises the
full user-fed workflow the assignment spec calls for: no auto-ingestion,
create/import documents, character/NPC/location creation, user-defined
links with staleness tracking, chat-driven edits through the
proposed/approve/reject lifecycle, illustration generation + embed, export,
and the validator.
"""

from __future__ import annotations


def _make_campaign(client, name="Test Campaign"):
    resp = client.post("/campaigns", json={"name": name, "genre": "fantasy"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_new_campaign_starts_completely_empty(client):
    campaign = _make_campaign(client)
    detail = client.get(f"/campaigns/{campaign['id']}").json()
    assert detail["document_count"] == 0
    assert detail["character_count"] == 0
    docs = client.get(f"/campaigns/{campaign['id']}/documents").json()
    assert docs == []


def test_list_campaigns_reports_real_document_and_character_counts(client):
    """
    Regression test: GET /campaigns (the endpoint the homepage's campaign
    card grid actually calls) used to return document_count/character_count
    as always-missing fields -- only GET /campaigns/{id} (the detail
    endpoint) computed them. The frontend defaults a missing count to 0
    (`c.document_count ?? 0`), so every card on the homepage silently showed
    "0 documents · 0 characters" even for a campaign full of real content.
    """
    campaign = _make_campaign(client)
    client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "campaign_bible", "title": "The Bible", "content_html": "<h1>The Bible</h1>"},
    )
    client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria Nightwind"})
    client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Kael Draven"})

    listing = client.get("/campaigns").json()
    row = next(c for c in listing if c["id"] == campaign["id"])
    # 1 campaign_bible document + 2 character documents (character creation
    # also creates a backing Document, see create_character in main.py)
    assert row["document_count"] == 3
    assert row["character_count"] == 2


def test_create_blank_document(client):
    campaign = _make_campaign(client)
    resp = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "campaign_bible", "title": "The Shattered Crown", "content_html": "<h1>The Shattered Crown</h1><p>An empire in ruins.</p>"},
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["doc_type"] == "campaign_bible"
    assert doc["origin"] == "created"
    assert doc["active_version"]["version_number"] == 1
    assert "Shattered Crown" in doc["active_version"]["content_html"]


def test_create_document_with_no_content_still_gets_a_starter_body(client):
    campaign = _make_campaign(client)
    resp = client.post(f"/campaigns/{campaign['id']}/documents", json={"doc_type": "other", "title": "Blank Doc"})
    assert resp.status_code == 200
    assert "Blank Doc" in resp.json()["active_version"]["content_html"]


def test_import_document_requires_explicit_type_no_auto_classification(client):
    campaign = _make_campaign(client)
    resp = client.post(
        f"/campaigns/{campaign['id']}/documents/import",
        data={"doc_type": "session_log", "title": "Session 1 Notes"},
        files={"file": ("session1.txt", b"The party arrived at Blackspire Keep.", "text/plain")},
    )
    assert resp.status_code == 200, resp.text
    doc = resp.json()
    assert doc["doc_type"] == "session_log"
    assert doc["origin"] == "imported"


def test_import_document_missing_type_is_rejected(client):
    campaign = _make_campaign(client)
    resp = client.post(
        f"/campaigns/{campaign['id']}/documents/import",
        data={"title": "No Type"},
        files={"file": ("x.txt", b"content", "text/plain")},
    )
    assert resp.status_code == 422  # doc_type is a required Form field


def test_create_character_creates_backing_document(client):
    campaign = _make_campaign(client)
    resp = client.post(
        f"/campaigns/{campaign['id']}/characters",
        json={"name": "Aria Nightwood", "race": "Elf", "char_class": "Ranger", "level": 3, "description": "A scout."},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["character"]["name"] == "Aria Nightwood"
    assert body["document"]["doc_type"] == "character"
    assert body["character"]["document_id"] == body["document"]["id"]

    listed = client.get(f"/campaigns/{campaign['id']}/characters").json()
    assert len(listed) == 1


def test_create_npc_and_location(client):
    campaign = _make_campaign(client)
    loc = client.post(f"/campaigns/{campaign['id']}/locations", json={"name": "Blackspire Keep"}).json()
    npc = client.post(
        f"/campaigns/{campaign['id']}/npcs",
        json={"name": "Castellan Vey", "role": "Keep warden", "related_location_id": loc["location"]["id"]},
    ).json()
    assert npc["npc"]["related_location_id"] == loc["location"]["id"]


def test_link_creation_and_staleness_flips_on_target_edit_then_resyncs(client):
    campaign = _make_campaign(client)
    bible = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "campaign_bible", "title": "Bible", "content_html": "<h1>Bible</h1><p>Original lore.</p>"},
    ).json()
    char = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria"}).json()
    char_doc_id = char["document"]["id"]

    link = client.post(
        "/links",
        json={"source_document_id": char_doc_id, "target_document_id": bible["id"], "relationship_type": "references", "note": "mentions the Fall of Eldoria"},
    ).json()
    assert link["status"] == "synced"
    assert link["synced_version_number"] == 1

    # Edit the bible via chat -> creates a PROPOSED version, link still synced (nothing active yet)
    chat_resp = client.post(f"/documents/{bible['id']}/chat", json={"message": "Add a new faction: the Ashen Concord."})
    assert chat_resp.status_code == 200, chat_resp.text
    chat_body = chat_resp.json()
    assert chat_body["status"] == "awaiting_approval"
    version_id = chat_body["version"]["id"]

    still = client.get(f"/links/{link['id']}").json()
    assert still["status"] == "synced"  # PROPOSED doesn't affect links yet

    # Approve -> bible moves to v2 ACTIVE -> inbound link should flip stale
    approve_resp = client.post(f"/documents/{bible['id']}/versions/{version_id}/approve")
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["links_flagged_stale"] == 1

    now_stale = client.get(f"/links/{link['id']}").json()
    assert now_stale["status"] == "stale"
    assert now_stale["synced_version_number"] == 1  # unchanged, target is now at v2

    bible_after = client.get(f"/documents/{bible['id']}").json()
    assert bible_after["active_version"]["version_number"] == 2
    assert "Ashen Concord" in bible_after["active_version"]["content_html"]

    # Resync clears staleness
    resynced = client.post(f"/links/{link['id']}/resync").json()
    assert resynced["status"] == "synced"
    assert resynced["synced_version_number"] == 2

    # validator agrees
    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    assert report["coherent"] is True
    assert report["stale_links"] == 0


def test_reject_discards_proposed_version_and_leaves_active_untouched(client):
    campaign = _make_campaign(client)
    doc = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "other", "title": "Notes", "content_html": "<h1>Notes</h1><p>Original.</p>"},
    ).json()

    chat_body = client.post(f"/documents/{doc['id']}/chat", json={"message": "Rewrite this entirely."}).json()
    version_id = chat_body["version"]["id"]

    reject_resp = client.post(f"/documents/{doc['id']}/versions/{version_id}/reject")
    assert reject_resp.status_code == 200
    assert reject_resp.json()["status"] == "rejected"

    # proposed version is gone; active is still v1 with original content
    versions = client.get(f"/documents/{doc['id']}/versions").json()
    assert all(v["id"] != version_id for v in versions)
    current = client.get(f"/documents/{doc['id']}").json()
    assert current["active_version"]["version_number"] == 1
    assert "Original" in current["active_version"]["content_html"]


def test_approving_a_version_that_is_not_proposed_is_rejected(client):
    campaign = _make_campaign(client)
    doc = client.post(f"/campaigns/{campaign['id']}/documents", json={"doc_type": "other", "title": "X"}).json()
    active_id = doc["active_version"]["id"]
    resp = client.post(f"/documents/{doc['id']}/versions/{active_id}/approve")
    assert resp.status_code == 409


def test_illustration_generation_and_embed(client, monkeypatch, fake_client, tmp_path):
    import image_gen
    import main as main_module

    monkeypatch.setattr(image_gen, "generate_illustration", lambda prompt, **kw: (b"fake-image-bytes", "image/png"))
    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")

    campaign = _make_campaign(client)
    char = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Kael", "content_html": "<h1>Kael</h1><p>A brooding warrior.</p>"}).json()

    resp = client.post(
        "/illustrations",
        json={"entity_type": "character", "entity_id": char["character"]["id"], "prompt": "a brooding elven warrior, portrait"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["embedded"] is True
    assert body["superdocs_image_url"].startswith("https://fake-superdocs.test/images/")
    assert body["local_image_url"].startswith("http://localhost:8001/static/illustrations/")

    doc_after = client.get(f"/documents/{char['document']['id']}").json()
    assert "<img" in doc_after["active_version"]["content_html"]
    assert doc_after["active_version"]["version_number"] == 2
    # embedded HTML uses our own reliably-reachable copy, not the SuperDocs
    # URL -- see main.py's generate_illustration comment: this app's own
    # document viewer renders that HTML directly in the browser, and a
    # plain anonymous fetch of the SuperDocs storage URL has been observed
    # 403'ing (GCS object ACL not actually public despite SuperDocs' docs).
    assert body["local_image_url"] in doc_after["active_version"]["content_html"]
    assert body["superdocs_image_url"] not in doc_after["active_version"]["content_html"]

    char_after = client.get(f"/campaigns/{campaign['id']}/characters").json()[0]
    assert char_after["image_url"] == body["local_image_url"]


def test_export_single_document(client):
    campaign = _make_campaign(client)
    doc = client.post(f"/campaigns/{campaign['id']}/documents", json={"doc_type": "other", "title": "Session 1"}).json()
    resp = client.get(f"/documents/{doc['id']}/export", params={"format": "docx"})
    assert resp.status_code == 200
    assert resp.content == b"FAKE-DOCX-EXPORT-CONTENT"
    assert "attachment" in resp.headers["content-disposition"]


def test_export_zip_rejected_for_single_document(client):
    campaign = _make_campaign(client)
    doc = client.post(f"/campaigns/{campaign['id']}/documents", json={"doc_type": "other", "title": "X"}).json()
    resp = client.get(f"/documents/{doc['id']}/export", params={"format": "zip"})
    assert resp.status_code == 400


def test_campaign_export_bundles_zip_with_manifest(client):
    import zipfile
    import io

    campaign = _make_campaign(client)
    bible = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "campaign_bible", "title": "Bible"},
    ).json()
    char = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria"}).json()
    client.post(
        "/links",
        json={"source_document_id": char["document"]["id"], "target_document_id": bible["id"], "relationship_type": "belongs_to_campaign"},
    )

    resp = client.get(f"/campaigns/{campaign['id']}/export", params={"format": "docx"})
    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "MANIFEST.txt" in names
    assert any(n.startswith("Characters/") for n in names)
    manifest = zf.read("MANIFEST.txt").decode("utf-8")
    assert "Aria" in manifest or "Bible" in manifest


def test_campaign_export_with_no_documents_is_rejected(client):
    campaign = _make_campaign(client)
    resp = client.get(f"/campaigns/{campaign['id']}/export")
    assert resp.status_code == 409


def test_full_showcase_scenario_bible_two_characters_and_illustration(client, monkeypatch):
    """Mirrors the assignment's minimum showcase: a Campaign Bible, two
    linked character sheets, and at least one generated illustration,
    exported as a coherent cross-referenced set."""
    import image_gen

    monkeypatch.setattr(image_gen, "generate_illustration", lambda prompt, **kw: (b"fake-bytes", "image/png"))

    campaign = _make_campaign(client, name="The Shattered Crown")
    bible = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": "campaign_bible", "title": "Campaign Bible", "content_html": "<h1>Campaign Bible</h1><p>An empire in ruins.</p>"},
    ).json()

    aria = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria Nightwood", "race": "Elf", "char_class": "Ranger"}).json()
    kael = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Kael Ashborn", "race": "Human", "char_class": "Warrior"}).json()

    for char in (aria, kael):
        link = client.post(
            "/links",
            json={"source_document_id": char["document"]["id"], "target_document_id": bible["id"], "relationship_type": "belongs_to_campaign"},
        )
        assert link.status_code == 200

    illus = client.post(
        "/illustrations",
        json={"entity_type": "character", "entity_id": aria["character"]["id"], "prompt": "elf ranger portrait"},
    )
    assert illus.status_code == 200
    assert illus.json()["embedded"] is True

    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    assert report["document_count"] == 3
    assert report["total_links"] == 2
    assert report["coherent"] is True

    export_resp = client.get(f"/campaigns/{campaign['id']}/export")
    assert export_resp.status_code == 200
