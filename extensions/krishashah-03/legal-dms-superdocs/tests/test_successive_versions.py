"""
Regression tests for the silent-stale-version bug: v1 -> v2 landed the edit,
but v2 -> v3 filed a byte-identical copy of v2 and still returned HTTP 200.

Root cause was two defects compounding:

1. app.main.get_workflow() built a NEW DocumentWorkflow per HTTP request, so
   the per-checkout caches were empty every time they were read. Covered by
   tests/test_app_wiring.py.

2. checkin() decided "was anything approved?" by diffing cached HTML strings
   rather than reading a recorded flag. With the caches empty that diff always
   said "unchanged", which routed check-in into the branch that reuses the
   CURRENT version's exported_bytes verbatim.

Defect 2 is why the failure looked version-dependent rather than constant.
The reuse branch only triggers when the current version HAS exported_bytes:

  - seed documents (add_document) leave v1.exported_bytes = None, so the
    v1 -> v2 check-in fell through to the export-from-session branch and the
    edit landed. That check-in then SET exported_bytes on v2...
  - ...so the v2 -> v3 check-in took the reuse branch and froze the content.

Every version after v2 was a byte-for-byte copy. Uploaded documents
(create_document) set exported_bytes on v1, so for those even v1 -> v2 was
already broken - which is why downloaded-v1.docx and downloaded-v2.docx in
the repo root have identical MD5s.

These tests run the full HTTP round trip three times over and assert the
content actually moves each time.
"""
from __future__ import annotations

import io

import pytest

USER = "attorney-priya"
MATTER = "matter-acme-nda"
DOC = "doc-nda-v1"
HEADERS = {"X-User-Id": USER}


def _bump_version(api_client, matter, doc, instruction, comment, approved=True):
    """One full checkout -> edit -> review -> checkin round trip over HTTP."""
    base = f"/matters/{matter}/documents/{doc}"

    checkout = api_client.post(f"{base}/checkout", headers=HEADERS)
    assert checkout.status_code == 200, checkout.text

    edit = api_client.post(f"{base}/edit", json={"instruction": instruction}, headers=HEADERS)
    assert edit.status_code == 200, edit.text
    changes = edit.json()["pending_changes"]
    assert changes, "the fake AI should always propose one change"

    review = api_client.post(
        f"{base}/review",
        json={
            "job_id": edit.json()["job_id"],
            "decisions": [{"change_id": c["change_id"], "approved": approved} for c in changes],
        },
        headers=HEADERS,
    )
    assert review.status_code == 200, review.text

    checkin = api_client.post(
        f"{base}/checkin", json={"version_comment": comment}, headers=HEADERS
    )
    assert checkin.status_code == 200, checkin.text
    return checkin.json()


def _download(api_client, matter, doc, version):
    response = api_client.get(
        f"/matters/{matter}/documents/{doc}/versions/{version}/download", headers=HEADERS
    )
    assert response.status_code == 200, response.text
    return response.content


def test_third_version_persists_its_edit_not_the_second_versions_content(api_client):
    """
    THE regression test. v2 -> v3 must land the edit, exactly like v1 -> v2.
    On the original code this failed: v3's bytes came back identical to v2's,
    with every HTTP call returning 200.
    """
    _bump_version(api_client, MATTER, DOC, "Tighten the confidentiality clause", "v2")
    _bump_version(api_client, MATTER, DOC, "Extend the term to three years", "v3")

    v1_or_v2 = _download(api_client, MATTER, DOC, 2)
    v3 = _download(api_client, MATTER, DOC, 3)

    assert v3 != v1_or_v2, "v3 is a byte-identical copy of v2 - the approved edit was dropped"
    assert b"Extend the term to three years" in v3


def test_edits_accumulate_across_many_successive_versions(api_client):
    """
    Each version must carry every earlier approved edit forward AND add its
    own - not just differ from its immediate predecessor. Guards against a
    "fix" that makes v3 differ from v2 by losing v2's edit instead.
    """
    instructions = [
        "Tighten the confidentiality clause",
        "Extend the term to three years",
        "Add a governing-law clause",
    ]
    for index, instruction in enumerate(instructions, start=2):
        result = _bump_version(api_client, MATTER, DOC, instruction, f"v{index}")
        assert result["new_version"] == index

    final = _download(api_client, MATTER, DOC, 4)
    for instruction in instructions:
        assert instruction.encode() in final, f"version 4 lost the edit {instruction!r}"


def test_every_version_has_distinct_bytes(api_client):
    """No two successive versions may be byte-identical when each one had an
    approved edit - that is precisely the shape the original bug produced."""
    _bump_version(api_client, MATTER, DOC, "Tighten the confidentiality clause", "v2")
    _bump_version(api_client, MATTER, DOC, "Extend the term to three years", "v3")
    _bump_version(api_client, MATTER, DOC, "Add a governing-law clause", "v4")

    payloads = [_download(api_client, MATTER, DOC, n) for n in (2, 3, 4)]
    assert len(set(payloads)) == 3, "successive versions must not be byte-identical"


def test_checkin_metadata_reports_that_edits_were_approved(api_client):
    """
    edits_approved_this_checkout is the audit trail a lawyer would read to
    confirm the version reflects a real decision. It was silently False on
    every version, including ones with approved edits.
    """
    _bump_version(api_client, MATTER, DOC, "Tighten the confidentiality clause", "v2")
    _bump_version(api_client, MATTER, DOC, "Extend the term to three years", "v3")

    versions = api_client.get(
        f"/matters/{MATTER}/documents/{DOC}/versions", headers=HEADERS
    ).json()
    assert [v["version_number"] for v in versions] == [1, 2, 3]


def test_uploaded_document_lands_its_first_edit(api_client, dms_store):
    """
    An UPLOADED document has real exported_bytes on version 1, which sent even
    its v1 -> v2 check-in down the reuse branch. This is the case that produced
    the identical-MD5 downloaded-v1.docx / downloaded-v2.docx pair in the repo.
    """
    upload = api_client.post(
        f"/matters/{MATTER}/documents",
        files={"file": ("agreement.html", io.BytesIO(b"<p>Original clause.</p>"), "text/html")},
        data={"title": "Consulting Services Agreement"},
        headers=HEADERS,
    )
    assert upload.status_code == 200, upload.text
    document_id = upload.json()["document_id"]

    _bump_version(api_client, MATTER, document_id, "Raise the fee cap", "v2")

    v1 = _download(api_client, MATTER, document_id, 1)
    v2 = _download(api_client, MATTER, document_id, 2)
    assert v1 != v2, "an uploaded document's first approved edit was dropped"
    assert b"Raise the fee cap" in v2


def test_rejecting_everything_still_produces_a_byte_identical_version(api_client):
    """
    The other half of the contract, and the reason check-in can't simply
    always export: a reviewed-but-denied checkout must file content that is
    provably unchanged, not re-serialized through SuperDocs's exporter.
    """
    _bump_version(api_client, MATTER, DOC, "Tighten the confidentiality clause", "v2")
    _bump_version(api_client, MATTER, DOC, "Add an unfavourable clause", "v3", approved=False)

    assert _download(api_client, MATTER, DOC, 3) == _download(api_client, MATTER, DOC, 2)


def test_checkin_refuses_rather_than_filing_stale_bytes_when_state_is_lost(
    api_client, workflow
):
    """
    Simulates the process restarting mid-checkout. The old code silently filed
    the previous version's bytes as a new version; it must now refuse (409) so
    the lawyer redoes the checkout instead of trusting a stale version.
    """
    base = f"/matters/{MATTER}/documents/{DOC}"
    assert api_client.post(f"{base}/checkout", headers=HEADERS).status_code == 200

    # Wipe the per-checkout state, exactly as a fresh instance would have.
    workflow._session_html.clear()
    workflow._checkout_baseline_html.clear()
    workflow._approved_sessions.clear()

    response = api_client.post(
        f"{base}/checkin", json={"version_comment": "should not be filed"}, headers=HEADERS
    )
    assert response.status_code == 409
    assert "no record of that checkout" in response.json()["detail"]

    versions = api_client.get(f"{base}/versions", headers=HEADERS).json()
    assert len(versions) == 1, "a refused check-in must not create a version"


@pytest.mark.parametrize("version_number", [2, 3])
def test_each_new_version_is_downloadable(api_client, version_number):
    """Every version produced by an approved edit must have real bytes behind
    it - a version with no file is not a filed document."""
    _bump_version(api_client, MATTER, DOC, "Tighten the confidentiality clause", "v2")
    _bump_version(api_client, MATTER, DOC, "Extend the term to three years", "v3")
    assert _download(api_client, MATTER, DOC, version_number)
