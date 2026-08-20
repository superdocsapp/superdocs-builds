"""
test_spec_gap_features.py -- coverage for the v3 "build it completely" spec
gap-list: manual save, [[Reference]] auto-linking + broken-ref detection,
document rename/change-type/delete cascade, search/filter/sort, campaign
patch + cover image, manual illustration upload, and the expanded
"Campaign Readiness" checklist validator. Uses the same FakeSuperDocsClient
+ in-memory SQLite fixtures as test_v2_api.py (see conftest.py).
"""

from __future__ import annotations


def _make_campaign(client, name="Readiness Test Campaign"):
    resp = client.post("/campaigns", json={"name": name, "genre": "fantasy"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _make_doc(client, campaign_id, doc_type, title, content_html=""):
    resp = client.post(
        f"/campaigns/{campaign_id}/documents",
        json={"doc_type": doc_type, "title": title, "content_html": content_html},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# -------------------------------------------------------------------------- #
# manual save
# -------------------------------------------------------------------------- #


def test_manual_save_creates_new_active_version(client):
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "campaign_bible", "The Bible", "<h1>The Bible</h1><p>v1</p>")

    resp = client.post(f"/documents/{doc['id']}/save", json={"content_html": "<h1>The Bible</h1><p>v2 edited by hand</p>", "change_summary": "Rewrote intro"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["document"]["active_version"]["version_number"] == 2
    assert "v2 edited by hand" in body["document"]["active_version"]["content_html"]

    versions = client.get(f"/documents/{doc['id']}/versions").json()
    assert len(versions) == 2
    assert versions[0]["status"] == "active"  # newest first
    assert versions[1]["status"] == "archived"


def test_manual_save_marks_inbound_links_stale(client):
    campaign = _make_campaign(client)
    bible = _make_doc(client, campaign["id"], "campaign_bible", "The Bible")
    session_log = _make_doc(client, campaign["id"], "session_log", "Session 1")

    link = client.post("/links", json={"source_document_id": session_log["id"], "target_document_id": bible["id"], "relationship_type": "references"})
    assert link.status_code == 200
    assert link.json()["status"] == "synced"

    client.post(f"/documents/{bible['id']}/save", json={"content_html": "<h1>The Bible</h1><p>changed</p>"})

    refreshed = client.get(f"/links/{link.json()['id']}").json()
    assert refreshed["status"] == "stale"


# -------------------------------------------------------------------------- #
# [[Reference]] detection
# -------------------------------------------------------------------------- #


def test_reference_syntax_resolves_and_creates_link(client):
    campaign = _make_campaign(client)
    keep = _make_doc(client, campaign["id"], "location", "Blackspire Keep")
    session_log = _make_doc(
        client, campaign["id"], "session_log", "Session 1",
        "<h1>Session 1</h1><p>The party arrived at [[Blackspire Keep]].</p>",
    )
    detail = client.get(f"/documents/{session_log['id']}").json()
    keep_id = keep["id"]
    assert f'href="/documents/{keep_id}"' in detail["active_version"]["content_html"]
    assert detail["broken_references"] == []

    links = client.get(f"/campaigns/{campaign['id']}/links").json()
    auto_links = [l for l in links if l["source_document_id"] == session_log["id"] and l["target_document_id"] == keep["id"]]
    assert len(auto_links) == 1
    assert auto_links[0]["relationship_type"] == "references"


def test_reference_resolves_against_imported_filename_style_title(client):
    # Reproduces the real-world case: a document imported from a file
    # keeps the raw filename as its title (numeric export-style prefix +
    # underscores), while a human writing [[Aric Stormborn]] in prose
    # naturally won't retype that whole filename. Normalized matching
    # should bridge the two without requiring an exact string match.
    campaign = _make_campaign(client)
    sheet = client.post(
        f"/campaigns/{campaign['id']}/documents/import",
        data={"doc_type": "character", "title": "02_Character_Sheet_Aric_Stormborn"},
        files={"file": ("02_Character_Sheet_Aric_Stormborn.txt", b"A ranger of Veyr.", "text/plain")},
    ).json()
    assert sheet["title"] == "02_Character_Sheet_Aric_Stormborn"

    bible = _make_doc(
        client, campaign["id"], "campaign_bible", "Bible",
        "<h1>Bible</h1><p>[[Aric Stormborn]] joins the party.</p>",
    )
    detail = client.get(f"/documents/{bible['id']}").json()
    assert detail["broken_references"] == []
    sheet_id = sheet["id"]
    assert f'href="/documents/{sheet_id}"' in detail["active_version"]["content_html"]


def test_reference_resolves_against_embedded_document_id_field(client):
    # Reproduces the real screenshot: the character sheet's own content has
    # a CONTROL/DETAIL table with a "Document ID" row reading "SC-PC-ARIC"
    # -- the original content's own internal ID scheme, which predates
    # [[Title]] references. A reference by that code, not by the (long,
    # filename-derived) title, should still resolve to this document.
    campaign = _make_campaign(client)
    sheet = _make_doc(
        client, campaign["id"], "character", "02_Character_Sheet_Aric_Stormborn",
        "<h1>Aric Stormborn</h1>"
        "<table><tr><th>Control</th><th>Detail</th></tr>"
        "<tr><td>Document ID</td><td>SC-PC-ARIC</td></tr></table>",
    )
    bible = _make_doc(client, campaign["id"], "campaign_bible", "Bible", "<h1>Bible</h1><p>[[SC-PC-ARIC]] guards the river.</p>")
    detail = client.get(f"/documents/{bible['id']}").json()
    assert detail["broken_references"] == []
    sheet_id = sheet["id"]
    assert f'href="/documents/{sheet_id}"' in detail["active_version"]["content_html"]

    # a ":section-anchor" suffix on the code still resolves to the same document
    doc2 = _make_doc(client, campaign["id"], "session_log", "Session 1", "<h1>Session 1</h1><p>[[SC-PC-ARIC:4-SIGNS]] appear.</p>")
    detail2 = client.get(f"/documents/{doc2['id']}").json()
    assert detail2["broken_references"] == []


def test_relink_document_references_updates_stale_stored_html(client):
    # Reproduces the exact bug reported: a document's stored content_html
    # was written before a document existed to resolve against, so the raw
    # [[Code]] text sits there un-linkified even after that target document
    # shows up later. A live re-scan (broken_references on GET) correctly
    # reports it as resolvable, but the actual rendered HTML is untouched
    # until something explicitly re-processes and re-saves it.
    campaign = _make_campaign(client)
    bible = _make_doc(client, campaign["id"], "campaign_bible", "Bible", "<h1>Bible</h1><p>[[Aric Stormborn]] guards the river.</p>")

    # confirm it starts broken (target doesn't exist yet) and NOT clickable
    before = client.get(f"/documents/{bible['id']}").json()
    assert "Aric Stormborn" in before["broken_references"]
    assert "doc-reference" not in before["active_version"]["content_html"]

    sheet = _make_doc(client, campaign["id"], "character", "Aric Stormborn")

    # the live re-scan now says it's resolvable...
    after_target_exists = client.get(f"/documents/{bible['id']}").json()
    assert after_target_exists["broken_references"] == []
    # ...but the STORED html is still the old, non-clickable text, because
    # nothing has re-saved the document since the target appeared
    assert "doc-reference" not in after_target_exists["active_version"]["content_html"]

    # relink-references is the explicit action that closes that gap
    result = client.post(f"/documents/{bible['id']}/relink-references")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["changed"] is True
    assert body["resolved_reference_count"] == 1
    assert body["broken_references"] == []
    sheet_id = sheet["id"]
    assert f'href="/documents/{sheet_id}"' in body["document"]["active_version"]["content_html"]

    # and a real DocumentLink now exists
    links = client.get(f"/campaigns/{campaign['id']}/links").json()
    assert any(l["source_document_id"] == bible["id"] and l["target_document_id"] == sheet_id for l in links)


def test_relink_campaign_references_processes_every_document(client):
    campaign = _make_campaign(client)
    # doc_a is created BEFORE its target exists, so its stored content_html
    # keeps the literal, un-linkified [[Blackspire Keep]] text -- exactly
    # the "stale content" scenario relink-references exists to fix.
    doc_a = _make_doc(client, campaign["id"], "session_log", "Session 1", "<h1>Session 1</h1><p>[[Blackspire Keep]]</p>")
    doc_b = _make_doc(client, campaign["id"], "session_log", "Session 2", "<h1>Session 2</h1><p>[[Nobody Real]]</p>")
    _make_doc(client, campaign["id"], "location", "Blackspire Keep")

    resp = client.post(f"/campaigns/{campaign['id']}/relink-references")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["documents_scanned"] == 3
    assert body["total_resolved_references"] >= 1
    assert body["total_broken_references"] >= 1

    detail_a = client.get(f"/documents/{doc_a['id']}").json()
    assert detail_a["broken_references"] == []
    detail_b = client.get(f"/documents/{doc_b['id']}").json()
    assert "Nobody Real" in detail_b["broken_references"]


def test_reference_ambiguous_substring_match_stays_unresolved(client):
    # Two different documents both normalize to contain "kael" -- resolving
    # to either one would be a silent guess, so this should stay unresolved
    # rather than picking one arbitrarily.
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "npc", "05_NPC_Dossier_Lord_Kael_Veyr")
    _make_doc(client, campaign["id"], "location", "09_Location_Keep_of_Kael")
    doc = _make_doc(client, campaign["id"], "session_log", "Session 1", "<h1>Session 1</h1><p>[[Kael]] appears.</p>")
    detail = client.get(f"/documents/{doc['id']}").json()
    assert "Kael" in detail["broken_references"]


def test_reference_to_unknown_title_is_flagged_broken(client):
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "session_log", "Session 1", "<h1>Session 1</h1><p>They met [[Nobody Real]].</p>")
    detail = client.get(f"/documents/{doc['id']}").json()
    assert "Nobody Real" in detail["broken_references"]
    assert "broken-reference" in detail["active_version"]["content_html"]


def test_reference_links_resync_when_content_changes(client):
    campaign = _make_campaign(client)
    keep = _make_doc(client, campaign["id"], "location", "Blackspire Keep")
    doc = _make_doc(client, campaign["id"], "session_log", "Session 1", "<h1>Session 1</h1><p>[[Blackspire Keep]]</p>")

    links_before = client.get(f"/campaigns/{campaign['id']}/links").json()
    assert len(links_before) == 1

    # remove the reference on manual save -- the auto link should disappear
    client.post(f"/documents/{doc['id']}/save", json={"content_html": "<h1>Session 1</h1><p>no more references here</p>"})
    links_after = client.get(f"/campaigns/{campaign['id']}/links").json()
    assert len(links_after) == 0


# -------------------------------------------------------------------------- #
# reference registry: [[DOC:SECTION]] anchors + bare entity/location codes
# -------------------------------------------------------------------------- #


def test_doc_section_reference_resolves_to_heading_anchor_with_clean_label(client):
    # [[SC-BIBLE:6-MAGIC]] should open the Bible AND jump straight to its
    # "Magic, Oaths, and the Ward Network" heading -- not just the doc top.
    bible = _make_doc(
        client, _make_campaign(client)["id"], "campaign_bible", "The Shattered Crown - Campaign Bible",
        "<table><tr><td>Document ID</td><td>SC-BIBLE</td></tr></table>"
        "<h2>Key Locations</h2><p>...</p>"
        "<h2>Magic, Oaths, and the Ward Network</h2><p>Ward magic details.</p>",
    )
    session_log = _make_doc(
        client, bible["campaign_id"], "session_log", "Session 1",
        "<h1>Session 1</h1><p>See [[SC-BIBLE:6-MAGIC]] for the ward rules.</p>",
    )
    detail = client.get(f"/documents/{session_log['id']}").json()
    html = detail["active_version"]["content_html"]
    assert detail["broken_references"] == []
    assert f'href="/documents/{bible["id"]}#magic-oaths-and-the-ward-network"' in html
    assert "Magic, Oaths, and the Ward Network" in html
    # raw ID code kept internally (data-ref-title) but must NOT be the visible link text
    assert ">SC-BIBLE:6-MAGIC<" not in html
    assert 'data-ref-title="SC-BIBLE:6-MAGIC"' in html


def test_bare_entity_code_resolves_into_campaign_bible_section(client):
    # LOC-VEYR has no document of its own -- it's a location entry inside
    # the Campaign Bible's "Key Locations" section (per the real pack).
    campaign = _make_campaign(client)
    bible = _make_doc(
        client, campaign["id"], "campaign_bible", "Campaign Bible",
        "<h2>Key Locations</h2><p>Veyr, City of Rain -- capital of the realm.</p>",
    )
    log = _make_doc(client, campaign["id"], "session_log", "Session 2", "<p>They travel toward [[LOC-VEYR]].</p>")
    detail = client.get(f"/documents/{log['id']}").json()
    assert detail["broken_references"] == []
    html = detail["active_version"]["content_html"]
    assert f'href="/documents/{bible["id"]}#key-locations"' in html
    assert "Campaign Bible: Key Locations" in html


def test_entity_code_ambiguous_across_non_bible_documents_stays_unresolved(client):
    # Two non-bible documents both have a heading matching the keyword --
    # genuinely ambiguous, no campaign_bible present to break the tie.
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "npc", "Faction Notes A", "<h2>The Lantern Concord</h2><p>...</p>")
    _make_doc(client, campaign["id"], "location", "Faction Notes B", "<h2>Lantern Rumors</h2><p>...</p>")
    log = _make_doc(client, campaign["id"], "session_log", "Session 1", "<p>[[FAC-LANTERN]] is mentioned.</p>")
    detail = client.get(f"/documents/{log['id']}").json()
    assert "FAC-LANTERN" in detail["broken_references"]


def test_entity_code_prefers_campaign_bible_when_ambiguous_elsewhere(client):
    # Same ambiguous setup, but WITH a campaign_bible match too -- per the
    # pack's convention, the bible wins as the canonical "world index".
    campaign = _make_campaign(client)
    bible = _make_doc(client, campaign["id"], "campaign_bible", "Bible", "<h2>Factions</h2><p>The Lantern Concord controls the docks.</p>")
    _make_doc(client, campaign["id"], "npc", "Extra Notes", "<h2>Lantern Rumors</h2><p>...</p>")
    log = _make_doc(client, campaign["id"], "session_log", "Session 1", "<p>[[FAC-LANTERN]] is mentioned.</p>")
    detail = client.get(f"/documents/{log['id']}").json()
    assert detail["broken_references"] == []
    assert f'href="/documents/{bible["id"]}#factions"' in detail["active_version"]["content_html"]


def test_human_written_reference_keeps_its_own_text_as_link_label(client):
    campaign = _make_campaign(client)
    keep = _make_doc(client, campaign["id"], "location", "Blackspire Keep")
    doc = _make_doc(client, campaign["id"], "session_log", "S1", "<p>They reached [[Blackspire Keep]].</p>")
    html = client.get(f"/documents/{doc['id']}").json()["active_version"]["content_html"]
    assert ">Blackspire Keep<" in html  # human title untouched, not rewritten to some other label


# -------------------------------------------------------------------------- #
# chat-edit: proposed changes that ADD content (not just find/replace)
# -------------------------------------------------------------------------- #


def test_chat_edit_insert_new_section_is_previewable_and_applies_on_approve(client):
    # Reproduces the real bug: asking the AI to *add* a brand-new section
    # comes back from SuperDocs as an insert (empty old_html), which the
    # old merge code silently dropped -- the "proposal" looked identical to
    # the current doc, and approving it bumped the version number with no
    # actual content change. FakeSuperDocsClient.chat_async simulates this
    # shape for any message matching "add/insert ... section".
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "campaign_bible", "The Bible", "<h1>The Bible</h1><p>Intro text.</p>")

    resp = client.post(f"/documents/{doc['id']}/chat", json={"message": 'add one more section "Summary" and under that give the summary of the document'})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "awaiting_approval"

    proposed = body["version"]
    assert proposed["status"] == "proposed"
    # the whole point: the proposed content must actually differ from the
    # current active content, and must contain the new section.
    active_before = client.get(f"/documents/{doc['id']}").json()["active_version"]["content_html"]
    assert proposed["content_html"] != active_before
    assert "Summary" in proposed["content_html"]
    assert "Intro text." in proposed["content_html"]  # original content preserved, not replaced

    approve_resp = client.post(f"/documents/{doc['id']}/versions/{proposed['id']}/approve")
    assert approve_resp.status_code == 200, approve_resp.text

    detail = client.get(f"/documents/{doc['id']}").json()
    assert detail["active_version"]["version_number"] == proposed["version_number"]
    assert "Summary" in detail["active_version"]["content_html"]
    assert "Intro text." in detail["active_version"]["content_html"]


# -------------------------------------------------------------------------- #
# rename / change-type / delete
# -------------------------------------------------------------------------- #


def test_patch_document_renames_and_changes_type(client):
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "other", "Untitled")
    resp = client.patch(f"/documents/{doc['id']}", json={"title": "Renamed Doc", "doc_type": "campaign_bible"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Renamed Doc"
    assert body["doc_type"] == "campaign_bible"


def test_delete_document_cascades(client):
    campaign = _make_campaign(client)
    char = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria", "description": "scout"}).json()
    doc_id = char["document"]["id"]

    resp = client.delete(f"/documents/{doc_id}")
    assert resp.status_code == 200

    assert client.get(f"/documents/{doc_id}").status_code == 404
    characters = client.get(f"/campaigns/{campaign['id']}/characters").json()
    assert characters == []


def test_delete_document_removes_links_and_nulls_embedded_illustration(client):
    campaign = _make_campaign(client)
    a = _make_doc(client, campaign["id"], "npc", "Villain")
    b = _make_doc(client, campaign["id"], "location", "Lair")
    link = client.post("/links", json={"source_document_id": a["id"], "target_document_id": b["id"]}).json()

    client.delete(f"/documents/{b['id']}")
    assert client.get(f"/links/{link['id']}").status_code == 404


# -------------------------------------------------------------------------- #
# search / filter / sort
# -------------------------------------------------------------------------- #


def test_document_list_search_filter_sort(client):
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "npc", "Zara the Wanderer")
    _make_doc(client, campaign["id"], "npc", "Aldric the Smith")
    _make_doc(client, campaign["id"], "location", "The Wandering Oasis")

    all_sorted = client.get(f"/campaigns/{campaign['id']}/documents?sort=name").json()
    assert [d["title"] for d in all_sorted] == ["Aldric the Smith", "The Wandering Oasis", "Zara the Wanderer"]

    only_npcs = client.get(f"/campaigns/{campaign['id']}/documents?doc_type=npc").json()
    assert {d["title"] for d in only_npcs} == {"Zara the Wanderer", "Aldric the Smith"}

    searched = client.get(f"/campaigns/{campaign['id']}/documents?q=wander").json()
    assert {d["title"] for d in searched} == {"Zara the Wanderer", "The Wandering Oasis"}


# -------------------------------------------------------------------------- #
# campaign patch + cover image
# -------------------------------------------------------------------------- #


def test_patch_campaign_updates_fields(client):
    campaign = _make_campaign(client)
    resp = client.patch(f"/campaigns/{campaign['id']}", json={"description": "Updated blurb", "setting": "A frozen wasteland"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "Updated blurb"
    assert body["setting"] == "A frozen wasteland"


def test_upload_campaign_cover_image(client):
    campaign = _make_campaign(client)
    resp = client.post(
        f"/campaigns/{campaign['id']}/cover-image",
        files={"file": ("cover.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cover_image"]


# -------------------------------------------------------------------------- #
# manual illustration upload
# -------------------------------------------------------------------------- #


def test_manual_illustration_upload_and_embed(client, tmp_path, monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")

    campaign = _make_campaign(client)
    npc = client.post(f"/campaigns/{campaign['id']}/npcs", json={"name": "Old Man Willow", "role": "hermit"}).json()

    resp = client.post(
        "/illustrations/upload",
        data={"entity_type": "npc", "entity_id": npc["npc"]["id"], "prompt": "a hermit", "embed": "true"},
        files={"file": ("willow.png", b"fake-bytes", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "upload"
    assert body["embedded"] is True

    doc = client.get(f"/documents/{npc['document']['id']}").json()
    assert "<img" in doc["active_version"]["content_html"]
    # The embedded <img> must point at our own reliably-reachable copy, not
    # the SuperDocs URL -- this app's own document viewer renders that HTML
    # directly in the browser (dangerouslySetInnerHTML), and a plain
    # anonymous fetch of the SuperDocs storage URL has been observed 403'ing.
    assert "http://localhost:8001/static/illustrations/" in doc["active_version"]["content_html"]
    assert body["superdocs_image_url"] not in doc["active_version"]["content_html"]

    npc_detail = client.get(f"/campaigns/{campaign['id']}/npcs").json()
    updated = next(n for n in npc_detail if n["id"] == npc["npc"]["id"])
    assert updated["image_url"] == body["local_image_url"]


def test_generate_illustration_embed_uses_local_url(client, tmp_path, monkeypatch):
    import image_gen
    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")
    monkeypatch.setattr(
        image_gen, "generate_illustration",
        lambda prompt, **kw: (b"fake-generated-bytes", "image/jpeg"),
    )

    campaign = _make_campaign(client)
    char = client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria"}).json()

    resp = client.post(
        "/illustrations",
        json={"entity_type": "character", "entity_id": char["character"]["id"], "prompt": "a scout", "embed": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["embedded"] is True

    doc = client.get(f"/documents/{char['document']['id']}").json()
    assert "http://localhost:8001/static/illustrations/" in doc["active_version"]["content_html"]
    assert body["superdocs_image_url"] not in doc["active_version"]["content_html"]


def test_generate_illustration_embed_preserves_real_heading_text(client, tmp_path, monkeypatch):
    """
    Regression test for a bug where embedding an illustration replaced the
    document's real heading with a literal "Please fill: Main Heading"
    placeholder. Root cause: the embed step used to ask SuperDocs' chat AI
    to "insert this image right after the main heading" -- an AI edit call
    -- and for the short, sparse documents a freshly-created Character/NPC/
    Location sheet actually is (the simplified creation forms only take a
    Name), the AI was observed rewriting the heading into a template
    placeholder instead of leaving it alone. The fix replaces that AI call
    with a deterministic regex insertion (_insert_image_after_heading) that
    never touches the surrounding text at all, so this locks in that the
    entity's real name always survives an embed untouched.
    """
    import image_gen
    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")
    monkeypatch.setattr(
        image_gen, "generate_illustration",
        lambda prompt, **kw: (b"fake-generated-bytes", "image/jpeg"),
    )

    campaign = _make_campaign(client)
    npc = client.post(f"/campaigns/{campaign['id']}/npcs", json={"name": "Old Man Willow"}).json()

    resp = client.post(
        "/illustrations",
        json={"entity_type": "npc", "entity_id": npc["npc"]["id"], "prompt": "a hermit", "embed": True},
    )
    assert resp.status_code == 200, resp.text

    doc = client.get(f"/documents/{npc['document']['id']}").json()
    html = doc["active_version"]["content_html"]
    # heading-anchor injection adds an id="..." attribute to the <h1>, so
    # check the visible text survives rather than an exact tag match
    assert ">Old Man Willow<" in html
    assert "Please fill" not in html


# -------------------------------------------------------------------------- #
# local illustration re-hosting (SuperDocs' upload-base64 URL has been
# observed coming back with the underlying storage object's ACL not
# actually public -- see main._save_local_illustration's docstring)
# -------------------------------------------------------------------------- #


def test_manual_illustration_upload_saves_local_copy_and_exposes_its_url(client, tmp_path, monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")

    campaign = _make_campaign(client)
    npc = client.post(f"/campaigns/{campaign['id']}/npcs", json={"name": "Old Man Willow", "role": "hermit"}).json()

    resp = client.post(
        "/illustrations/upload",
        data={"entity_type": "npc", "entity_id": npc["npc"]["id"], "prompt": "a hermit", "embed": "false"},
        files={"file": ("willow.png", b"fake-png-bytes", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["local_image_url"], "expected a local_image_url in the response"
    assert body["local_image_url"].startswith("http://localhost:8001/static/illustrations/")

    saved_files = list(tmp_path.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"fake-png-bytes"
    # the SuperDocs-returned URL is untouched -- still what gets embedded
    # into the document itself
    assert body["superdocs_image_url"]


def test_generate_illustration_saves_local_copy(client, tmp_path, monkeypatch):
    import image_gen
    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_BASE", "http://localhost:8001")
    monkeypatch.setattr(
        image_gen, "generate_illustration",
        lambda prompt, **kw: (b"fake-generated-bytes", "image/jpeg"),
    )

    campaign = _make_campaign(client)
    loc = client.post(f"/campaigns/{campaign['id']}/locations", json={"name": "Ghost Town"}).json()

    resp = client.post(
        "/illustrations",
        json={"entity_type": "location", "entity_id": loc["location"]["id"], "prompt": "a ghost town", "embed": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["local_image_url"], "expected a local_image_url in the response"
    saved_files = list(tmp_path.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"fake-generated-bytes"


# -------------------------------------------------------------------------- #
# expanded "Campaign Readiness" validator
# -------------------------------------------------------------------------- #


def test_readiness_checklist_flags_missing_coverage_on_empty_campaign(client):
    campaign = _make_campaign(client)
    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    assert report["ready"] is False
    labels_failing = {item["label"] for item in report["checklist"] if not item["ok"]}
    assert "Campaign Bible" in labels_failing
    assert "At least one character" in labels_failing


def test_readiness_checklist_flags_broken_reference_and_duplicate_titles(client):
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "campaign_bible", "The Bible", "<h1>The Bible</h1><p>[[Ghost Town]]</p>")
    _make_doc(client, campaign["id"], "location", "Duplicate Place")
    _make_doc(client, campaign["id"], "location", "Duplicate Place")

    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    assert len(report["broken_references"]) == 1
    assert report["broken_references"][0]["ref_title"] == "Ghost Town"
    assert len(report["duplicate_titles"]) == 1
    assert report["duplicate_titles"][0]["title"] == "Duplicate Place"
    assert report["ready"] is False


def test_readiness_checklist_flags_uncovered_illustrations(client):
    campaign = _make_campaign(client)
    client.post(f"/campaigns/{campaign['id']}/characters", json={"name": "Aria", "description": "scout"})
    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    uncovered_names = {u["name"] for u in report["uncovered_illustrations"]}
    assert "Aria" in uncovered_names
    labels_failing = {item["label"] for item in report["checklist"] if not item["ok"]}
    assert "Illustration: Aria" in labels_failing


# -------------------------------------------------------------------------- #
# document detail exposes its backing entity (for inline "Add Illustration")
# -------------------------------------------------------------------------- #


def test_document_detail_exposes_entity_info_for_location(client):
    campaign = _make_campaign(client)
    loc = client.post(f"/campaigns/{campaign['id']}/locations", json={"name": "Blackspire Keep", "description": "a ruin"}).json()
    detail = client.get(f"/documents/{loc['document']['id']}").json()
    assert detail["entity_type"] == "location"
    assert detail["entity_id"] == loc["location"]["id"]
    assert detail["entity_image_url"] is None


def test_document_detail_entity_info_is_null_for_campaign_bible(client):
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "campaign_bible", "The Bible")
    detail = client.get(f"/documents/{doc['id']}").json()
    assert detail["entity_type"] is None
    assert detail["entity_id"] is None


def test_generic_created_location_document_gets_backfilled_entity_row(client):
    # Reproduces the real bug: a document created/imported via the generic
    # path (doc_type="location") -- NOT via POST /campaigns/{id}/locations
    # -- has no backing Location row, so the "Add Illustration" section
    # never had anything to attach to and the doc was invisible to the
    # Locations tab. Opening the document should backfill the row.
    campaign = _make_campaign(client)
    doc = _make_doc(client, campaign["id"], "location", "Blackspire Keep", "<h1>Blackspire Keep</h1><p>a ruin</p>")

    detail = client.get(f"/documents/{doc['id']}").json()
    assert detail["entity_type"] == "location"
    assert detail["entity_id"]

    # backfilled and visible from the Locations tab too, not just the doc page
    locations = client.get(f"/campaigns/{campaign['id']}/locations").json()
    assert len(locations) == 1
    assert locations[0]["name"] == "Blackspire Keep"
    assert locations[0]["document_id"] == doc["id"]


def test_locations_tab_itself_triggers_backfill_without_opening_document(client):
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "npc", "Old Man Willow")
    npcs = client.get(f"/campaigns/{campaign['id']}/npcs").json()
    assert len(npcs) == 1
    assert npcs[0]["name"] == "Old Man Willow"


def test_readiness_checklist_counts_generically_created_documents(client):
    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "character", "Aric Stormborn")
    report = client.get(f"/campaigns/{campaign['id']}/validate").json()
    labels_failing = {item["label"] for item in report["checklist"] if not item["ok"]}
    assert "At least one character" not in labels_failing


# -------------------------------------------------------------------------- #
# ZIP export: Assets/ folder with real image bytes + rewritten manifest
# -------------------------------------------------------------------------- #


class _FakeImageResponse:
    def __init__(self, content: bytes, content_type: str):
        self.content = content
        self.headers = {"Content-Type": content_type}

    def raise_for_status(self):
        pass


def test_export_zip_includes_assets_folder_and_manifest_summary(client, monkeypatch):
    import io
    import zipfile

    import main as main_module

    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "campaign_bible", "The Bible", "<h1>The Bible</h1><p>[[Ghost Town]]</p>")
    loc = client.post(f"/campaigns/{campaign['id']}/locations", json={"name": "Blackspire Keep", "description": "a ruin"}).json()

    upload = client.post(
        "/illustrations/upload",
        data={"entity_type": "location", "entity_id": loc["location"]["id"], "prompt": "a ruined keep", "embed": "false"},
        files={"file": ("keep.png", b"fake-png-bytes", "image/png")},
    )
    assert upload.status_code == 200, upload.text

    monkeypatch.setattr(main_module.requests, "get", lambda url, timeout=20: _FakeImageResponse(b"fake-png-bytes", "image/png"))

    resp = client.get(f"/campaigns/{campaign['id']}/export?format=docx")
    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()

    asset_names = [n for n in names if n.startswith("Assets/")]
    assert len(asset_names) == 1
    assert "blackspire-keep-illustration" in asset_names[0]

    manifest = zf.read("MANIFEST.txt").decode("utf-8")
    assert f"Campaign: {campaign['name']}" in manifest
    assert "Export Version: 1.0" in manifest
    assert "Documents:" in manifest
    assert "Blackspire Keep" in manifest
    assert "Assets:" in manifest
    assert "Cross-references:" in manifest
    assert "1 unresolved" in manifest
    assert "Ghost Town" in manifest


def test_export_assets_use_local_bytes_not_the_broken_superdocs_url(client, monkeypatch, tmp_path):
    """
    Regression test for a real bug: the Assets/ export loop used to fetch
    i.superdocs_image_url over the network -- the storage.googleapis.com
    URL that (per _extract_image_url's docstring and the local-hosting
    workaround in generate_illustration/upload_illustration) has been
    observed 403'ing "AccessDenied" on an anonymous GET even though the
    SuperDocs upload that produced it succeeded. That fetch failure was
    swallowed by a bare `except Exception: continue`, so a campaign with a
    real, embedded illustration could export a zip with an empty Assets/
    folder and no error anywhere -- exactly what happened when this was run
    live (see demo_seed_live.py's actual output).

    Fix: read from the local copy on disk (local_image_path) first. This
    test proves that path is actually taken by making the network fetch
    fail loudly if it's ever called -- the export must still succeed with a
    populated Assets/ folder.
    """
    import io
    import zipfile

    import main as main_module

    monkeypatch.setattr(main_module, "ILLUSTRATIONS_DIR", str(tmp_path))

    def _network_fetch_should_never_be_called(url, timeout=20):
        raise AssertionError(f"export should read the local illustration copy, not fetch {url!r} over the network")

    monkeypatch.setattr(main_module.requests, "get", _network_fetch_should_never_be_called)

    campaign = _make_campaign(client)
    _make_doc(client, campaign["id"], "campaign_bible", "The Bible", "<h1>The Bible</h1>")
    loc = client.post(f"/campaigns/{campaign['id']}/locations", json={"name": "Blackspire Keep", "description": "a ruin"}).json()

    upload = client.post(
        "/illustrations/upload",
        data={"entity_type": "location", "entity_id": loc["location"]["id"], "prompt": "a ruined keep", "embed": "false"},
        files={"file": ("keep.png", b"real-local-bytes", "image/png")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["local_image_url"]  # local copy was actually saved

    resp = client.get(f"/campaigns/{campaign['id']}/export?format=docx")
    assert resp.status_code == 200, resp.text
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    asset_names = [n for n in zf.namelist() if n.startswith("Assets/")]
    assert len(asset_names) == 1
    assert zf.read(asset_names[0]) == b"real-local-bytes"


# -------------------------------------------------------------------------- #
# Campaign Assistant -- generates a draft, doesn't save anything by itself
# -------------------------------------------------------------------------- #


def test_campaign_assistant_generates_draft_with_suggested_title_and_type(client):
    campaign = _make_campaign(client)
    resp = client.post(f"/campaigns/{campaign['id']}/assistant", json={"message": 'Create an NPC named "Lady Mara Ilyr" who serves Lord Kael.'})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["content_html"]
    assert body["suggested_doc_type"] == "npc"
    assert body["suggested_title"] == "Lady Mara Ilyr"

    # nothing was saved to the campaign yet -- assistant only drafts
    docs = client.get(f"/campaigns/{campaign['id']}/documents").json()
    assert docs == []

    # the GM can then save the draft as a real document via the normal path
    created = client.post(
        f"/campaigns/{campaign['id']}/documents",
        json={"doc_type": body["suggested_doc_type"], "title": body["suggested_title"], "content_html": body["content_html"]},
    )
    assert created.status_code == 200, created.text
    assert created.json()["title"] == "Lady Mara Ilyr"


def test_campaign_assistant_message_history_is_retrievable(client):
    campaign = _make_campaign(client)
    client.post(f"/campaigns/{campaign['id']}/assistant", json={"message": "Summarize session 3."})
    messages = client.get(f"/campaigns/{campaign['id']}/assistant/messages").json()
    roles = [m["role"] for m in messages]
    assert roles == ["user", "assistant"]
    assert messages[0]["content"] == "Summarize session 3."
