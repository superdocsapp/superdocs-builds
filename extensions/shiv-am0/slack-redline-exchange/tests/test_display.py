from __future__ import annotations

import pytest

from redline.core.documents import title_from_filename
from redline.slack.cards import flatten_blocks_text
from tests.conftest import CAP_INSTRUCTION, build_harness, make_contract_docx

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Acme_Globex_MSA.docx", "Acme Globex MSA"),
        ("master-services-agreement.pdf", "Master Services Agreement"),
        ("NDA.docx", "NDA"),
        ("my contract.docx", "My Contract"),
        ("noextension", "Noextension"),
        (".docx", ".docx"),
    ],
)
def test_a_filename_becomes_a_readable_deal_name(filename, expected):
    """Acronyms keep their case; only all-lowercase words get capitalised."""
    assert title_from_filename(filename) == expected


async def test_a_new_deal_is_named_without_its_file_extension(tmp_path):
    """Otherwise messages read "added X.docx to Y.docx", which looks like a bug."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "Acme_Globex_MSA.docx", make_contract_docx())

    assert h.store.get_deal(deal["deal_id"]).name == "Acme Globex MSA"


async def test_cards_show_a_countable_version_not_a_uuid(tmp_path):
    """SuperDocs identifies versions by UUID; nobody can read that in a Slack message.

    The UUID stays in the record for traceability -- this only governs what is shown.
    """
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]
    assert h.store.get_deal(deal_id).display_version == "v1"

    job = await h.sim.run_command("vendor", f"propose {deal_id} {CAP_INSTRUCTION}")
    proposal = h.store.proposals_for_job(job["job_id"])[0]
    await h.sim.click("vendor", proposal.id, "approve")
    await h.sim.click("customer", proposal.id, "approve")

    assert h.store.get_deal(deal_id).display_version == "v2"
    outcome = [m for m in h.sim.shared_messages() if "updated to" in m.text][-1]
    assert "*v2*" in outcome.text


async def test_the_superdocs_version_id_survives_the_friendlier_display(tmp_path):
    """Traceability upstream must not be traded away for a readable card.

    The fake happens to label versions "v2" as well, so this drives the real case
    directly: a UUID from SuperDocs is kept verbatim while the card still counts.
    """
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    h.store.set_deal_version(deal_id, "b196b9f1-4aff-4394-8073-a8d50eacfef9")

    fresh = h.store.get_deal(deal_id)
    assert fresh.current_version == "b196b9f1-4aff-4394-8073-a8d50eacfef9"
    assert fresh.display_version == "v2", "the counter advances independently of the id"
    status = h.service.status(deal_id)
    assert status["current_version"] == "b196b9f1-4aff-4394-8073-a8d50eacfef9"
    assert status["version"] == "v2"


def test_an_older_database_gains_the_version_column(tmp_path):
    """The migration must be idempotent on a database created before this change."""
    import sqlite3

    path = tmp_path / "legacy.db"
    legacy = sqlite3.connect(path)
    legacy.execute(
        "CREATE TABLE deals (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
        " superdocs_session_id TEXT NOT NULL, original_filename TEXT NOT NULL,"
        " original_bytes BLOB NOT NULL, approval_policy TEXT NOT NULL,"
        " shared_channel_id TEXT NOT NULL, current_version TEXT NOT NULL DEFAULT 'v1',"
        " status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL)"
    )
    legacy.commit()
    legacy.close()

    from redline.core.store import Store

    store = Store(str(path))
    columns = {r["name"] for r in store._conn.execute("PRAGMA table_info(deals)")}
    assert "version_number" in columns
    Store(str(path))  # opening twice must not fail


async def test_the_start_card_carries_the_id_every_command_needs(tmp_path):
    """Every /redline verb takes a deal id first, so the card announcing a deal has to
    show one. Without it, the only way to drive the app is to open the database."""
    h = build_harness(tmp_path)
    deal = await h.sim.send_file_share("vendor", "Acme_Globex_MSA.docx", make_contract_docx())
    deal_id = deal["deal_id"]

    started = [m for m in h.sim.shared_messages() if "negotiation started" in m.text.lower()]
    assert started, "expected a deal-started message in the shared channel"

    card = started[-1]
    assert deal_id in card.text, "the deal id must survive in the message text"
    assert deal_id in flatten_blocks_text(card.blocks)
