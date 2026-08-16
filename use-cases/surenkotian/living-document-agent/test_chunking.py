"""
Offline tests for the chunk-boundary logic -- no API key needed. This is
the one piece of this build where a bug would silently defeat the whole
ownership guarantee, so it gets tested directly against the exact HTML
shapes observed from the real API (see PROOF_RUN.md), not synthetic markup.
"""

from chunking import chunk_map_excluding, find_section_chunk_ids, split_into_chunks

REAL_DOCUMENT_HTML = (
    '<h1 data-chunk-id="ef20f84f-a3e9-4149-86cb-d52ed76cb45d">Team Operations Dashboard</h1>\n'
    '<h2 data-chunk-id="84d98a95-db3d-45c9-ad20-5f0b92a301ee">Weekly Priorities</h2>\n'
    '<ol data-chunk-id="b34ba260-9486-472e-9673-c2e4b53b5ca3"><li>Item one.</li></ol>\n'
    '<h2 data-chunk-id="9267d12f-8918-4ee6-adba-3f5030b64bd6">Team Notes</h2>\n'
    '<p data-chunk-id="da73c3db-6086-4285-90cc-a42d6721b7b7">Some human note.</p>\n'
    '<h2 data-chunk-id="e756e234-b5fe-4f98-b12f-5191015f2f89">[AGENT-MAINTAINED] Live Service Status -- do not edit manually</h2>\n'
    '<table data-chunk-id="411f0464-77eb-4220-98b6-69e5f08de603"><tr><td>Operational</td></tr></table>'
)


def test_splits_every_top_level_chunk():
    chunks = split_into_chunks(REAL_DOCUMENT_HTML)
    ids = [c.chunk_id for c in chunks]
    assert ids == [
        "ef20f84f-a3e9-4149-86cb-d52ed76cb45d",
        "84d98a95-db3d-45c9-ad20-5f0b92a301ee",
        "b34ba260-9486-472e-9673-c2e4b53b5ca3",
        "9267d12f-8918-4ee6-adba-3f5030b64bd6",
        "da73c3db-6086-4285-90cc-a42d6721b7b7",
        "e756e234-b5fe-4f98-b12f-5191015f2f89",
        "411f0464-77eb-4220-98b6-69e5f08de603",
    ]


def test_finds_owned_section_heading_plus_table():
    section = find_section_chunk_ids(REAL_DOCUMENT_HTML, "[AGENT-MAINTAINED] Live Service Status")
    assert section == [
        "e756e234-b5fe-4f98-b12f-5191015f2f89",
        "411f0464-77eb-4220-98b6-69e5f08de603",
    ]


def test_section_stops_at_next_heading():
    """If there were a heading after the table, the section must not
    swallow it -- this is what makes the boundary a real boundary."""
    html_with_trailing_heading = REAL_DOCUMENT_HTML + '\n<h2 data-chunk-id="zzz">Unrelated Later Section</h2>'
    section = find_section_chunk_ids(html_with_trailing_heading, "[AGENT-MAINTAINED] Live Service Status")
    assert "zzz" not in section


def test_chunk_map_excluding_drops_only_the_owned_ids():
    owned = ["e756e234-b5fe-4f98-b12f-5191015f2f89", "411f0464-77eb-4220-98b6-69e5f08de603"]
    remaining = chunk_map_excluding(REAL_DOCUMENT_HTML, owned)
    assert set(remaining.keys()) == {
        "ef20f84f-a3e9-4149-86cb-d52ed76cb45d",
        "84d98a95-db3d-45c9-ad20-5f0b92a301ee",
        "b34ba260-9486-472e-9673-c2e4b53b5ca3",
        "9267d12f-8918-4ee6-adba-3f5030b64bd6",
        "da73c3db-6086-4285-90cc-a42d6721b7b7",
    }


def test_boundary_diff_catches_an_added_chunk_outside_the_section():
    """Regression test for the real bug found in PROOF_RUN.md: comparing
    only pre-existing keys missed a chunk that got ADDED outside the owned
    section. This proves the fix -- a naive dict equality check -- is
    sufficient to detect an added key, which is what living_doc_agent.py
    relies on."""
    owned = ["e756e234-b5fe-4f98-b12f-5191015f2f89", "411f0464-77eb-4220-98b6-69e5f08de603"]
    before = chunk_map_excluding(REAL_DOCUMENT_HTML, owned)
    html_with_stray_insert = REAL_DOCUMENT_HTML + '\n<p data-chunk-id="stray">Unexpected insert</p>'
    after = chunk_map_excluding(html_with_stray_insert, owned)
    assert before != after
    assert "stray" in after and "stray" not in before
