"""
Validation logic moved into main.py (POST /workspaces/{id}/validate,
function `validate_workspace`) as part of the Workspace-schema rebuild --
see validator.py's module docstring. The full validation logic (all five
checks + Finding creation + the low-confidence and missing-reference
paths) is exercised end-to-end in tests/test_main.py, which is a more
realistic test than a standalone validator module could be now that
validation reads live off the same DB the rest of the app writes to.

This file is kept (rather than deleted, which this sandbox would not
permit) as a placeholder so pytest collection doesn't break on an import
of the old validator.run_validation(session, client) signature, which no
longer exists.
"""


def test_validator_moved_into_main():
    import validator

    try:
        validator.run_validation()
    except RuntimeError as e:
        assert "superseded" in str(e)
    else:
        raise AssertionError("expected validator.run_validation to raise -- see test_main.py for real coverage")
