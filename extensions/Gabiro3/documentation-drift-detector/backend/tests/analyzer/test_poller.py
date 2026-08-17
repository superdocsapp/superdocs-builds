import pytest

from agents.analyzer.poller import CANCEL_STATUSES, Poller, RunCancelled
from agents.analyzer.finder import FindingOutput


class TestCancelSemantics:
    def test_cancelling_and_cancelled_both_halt(self):
        # 'cancelling' is the request; 'cancelled' is the settled state.
        # Both must stop work, or a resume could race a stop.
        assert "cancelling" in CANCEL_STATUSES
        assert "cancelled" in CANCEL_STATUSES

    def test_active_statuses_do_not_halt(self):
        assert "in_progress" not in CANCEL_STATUSES
        assert "pending" not in CANCEL_STATUSES

    def test_run_cancelled_is_not_an_error(self):
        # Callers distinguish a deliberate stop from a genuine failure.
        assert issubclass(RunCancelled, Exception)


class TestFindingNormalisation:
    """The Finder's schema defaults uuid-ish fields to "", which Postgres
    rejects for uuid columns ('length must be between 32..36 characters')."""

    def test_uuid_columns_are_declared(self):
        assert "change_fact_id" in Poller._UUID_COLUMNS
        assert "document_id" in Poller._UUID_COLUMNS

    def test_blank_uuid_fields_exist_on_the_model(self):
        out = FindingOutput(state="UNKNOWN")
        data = out.model_dump()
        for col in Poller._UUID_COLUMNS:
            assert col in data
            assert data[col] == ""

    def test_blank_is_falsy_so_normalisation_triggers(self):
        out = FindingOutput(state="UNKNOWN")
        data = out.model_dump()
        # This is the exact condition _persist_finding uses.
        assert all(not data.get(col) for col in Poller._UUID_COLUMNS)
