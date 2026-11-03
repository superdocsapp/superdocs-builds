from app.models import MetadataChange
from app.workflow.hash_chain import GENESIS_HASH, compute_entry_hash, verify_chain


def _chain_entries(rows):
    """Builds a properly-chained list of MetadataChange from
    (field_name, old, new, reason) tuples, for test setup."""
    entries = []
    prev_hash = GENESIS_HASH
    for i, (field_name, old, new, reason) in enumerate(rows):
        h = compute_entry_hash(prev_hash, "f1", field_name, old, new, "sha1abc", 1000.0 + i, reason, None)
        entries.append(
            MetadataChange(
                file_id="f1",
                field_name=field_name,
                old_value=old,
                new_value=new,
                version_sha1="sha1abc",
                timestamp=1000.0 + i,
                reason=reason,
                prev_hash=prev_hash,
                entry_hash=h,
            )
        )
        prev_hash = h
    return entries


def test_empty_chain_is_valid():
    result = verify_chain([])
    assert result.valid is True
    assert result.checked_count == 0


def test_intact_chain_of_several_entries_verifies():
    entries = _chain_entries(
        [
            ("counterparty_name", None, "Acme", "processed"),
            ("contract_value", None, "$1000", "processed"),
            ("contract_value", "$1000", "$2000", "reprocessed: new version"),
        ]
    )
    result = verify_chain(entries)
    assert result.valid is True
    assert result.checked_count == 3


def test_tampering_with_a_stored_field_breaks_verification():
    entries = _chain_entries([("counterparty_name", None, "Acme", "processed")])
    entries[0].new_value = "Globex"  # simulate someone editing the row directly
    result = verify_chain(entries)
    assert result.valid is False
    assert result.first_break_index == 0


def test_tampering_with_a_later_entry_does_not_hide_behind_earlier_valid_ones():
    entries = _chain_entries(
        [
            ("counterparty_name", None, "Acme", "processed"),
            ("contract_value", None, "$1000", "processed"),
        ]
    )
    entries[1].reason = "totally different reason"
    result = verify_chain(entries)
    assert result.valid is False
    assert result.first_break_index == 1


def test_deleting_a_middle_entry_breaks_the_prev_hash_link():
    entries = _chain_entries(
        [
            ("counterparty_name", None, "Acme", "processed"),
            ("contract_value", None, "$1000", "processed"),
            ("effective_date", None, "2026-01-15", "processed"),
        ]
    )
    del entries[1]  # simulate a row being deleted from the table
    result = verify_chain(entries)
    assert result.valid is False
    assert result.first_break_index == 1


def test_reordering_entries_breaks_verification():
    entries = _chain_entries(
        [
            ("counterparty_name", None, "Acme", "processed"),
            ("contract_value", None, "$1000", "processed"),
        ]
    )
    entries[0], entries[1] = entries[1], entries[0]
    result = verify_chain(entries)
    assert result.valid is False


def test_pre_migration_entries_with_no_hash_are_an_unverifiable_prefix_not_a_break():
    legacy = MetadataChange(
        file_id="f1",
        field_name="counterparty_name",
        old_value=None,
        new_value="Acme",
        version_sha1="sha1abc",
        timestamp=999.0,
        reason="processed",
        # entry_hash / prev_hash both None -- written before this feature existed
    )
    chained = _chain_entries([("contract_value", None, "$1000", "processed")])
    entries = [legacy] + chained
    result = verify_chain(entries)
    assert result.valid is True
    assert result.unverifiable_prefix_count == 1
    assert result.checked_count == 1


def test_same_inputs_produce_the_same_hash_deterministically():
    h1 = compute_entry_hash(GENESIS_HASH, "f1", "counterparty_name", None, "Acme", "sha1", 100.0, "processed", "sess-1")
    h2 = compute_entry_hash(GENESIS_HASH, "f1", "counterparty_name", None, "Acme", "sha1", 100.0, "processed", "sess-1")
    assert h1 == h2


def test_different_source_session_id_produces_a_different_hash():
    h1 = compute_entry_hash(GENESIS_HASH, "f1", "x", None, "v", "sha1", 100.0, "processed", "sess-1")
    h2 = compute_entry_hash(GENESIS_HASH, "f1", "x", None, "v", "sha1", 100.0, "processed", "sess-2")
    assert h1 != h2
