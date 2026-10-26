"""exec() must commit mutating statements even when they RETURN rows.

Only committing when a statement returned no rows meant that any
UPDATE/INSERT/DELETE ... RETURNING was silently rolled back at session close:
the call reported success and returned the affected rows, while the database
was left unchanged.
"""

import inspect

from core import db


class TestExecCommitsMutations:
    def test_commit_is_not_conditional_on_returns_rows(self):
        source = inspect.getsource(db.exec)
        commit_index = source.index("await session.commit()")
        # The commit must not sit inside the `if not result.returns_rows` arm.
        guarded = "if not result.returns_rows:\n            await session.commit()"
        assert guarded not in source

        # And it must run before the function returns its rows.
        return_index = source.rindex("return [dict(row._mapping)")
        assert commit_index < return_index

    def test_rows_are_still_returned(self):
        source = inspect.getsource(db.exec)
        assert "result.fetchall() if result.returns_rows else []" in source

    def test_docstring_states_the_no_rows_behaviour(self):
        assert "ResourceClosedError" in (db.exec.__doc__ or "")
